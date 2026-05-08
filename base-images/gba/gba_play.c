// gba_play: headless GBA harness with scripted input, optional savestate /
// cheats, and RAM dump.
//
// This is the agent-facing tool inside the benchmark substrate. The companion
// `gba_probe` tool stays minimal and is reserved for the determinism gate.
// `gba_play` carries the per-task driving logic: scripted button presses,
// savestate loading, optional cheat application, and a memory snapshot at end
// of run that the verifier (or the agent) can hash / inspect / diff.
//
// Build: see tools/gba_probe/build.sh (or substrate Dockerfile). Same defines
// must match libmgba's compilation flags or struct layouts diverge.
//
// Usage:
//
//   gba_play --rom <rom.gba> [--frames N]
//            [--input <input.txt>]
//            [--cheats <cheats.cht>]
//            [--state <save.ss1>]
//            [--dump-ram <out.bin>]
//
// Input file format: text, one event per line.
//   <frame> <+|-> <BUTTON>
// Buttons: A B SELECT START RIGHT LEFT UP DOWN L R
// Lines starting with '#' and blank lines are ignored.
// Multiple events on the same frame = multiple lines.
// Press is sticky until released — i.e. typical "hold A from frame 60 to 90"
// is `60 + A` and `90 - A`.

#include <mgba/core/cheats.h>
#include <mgba/core/config.h>
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/core/serialize.h>
#include <mgba/internal/gba/input.h>
#include <mgba-util/common.h>
#include <mgba-util/vfs.h>

#include <ctype.h>
#include <fcntl.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GBA_WIDTH 240
#define GBA_HEIGHT 160

static color_t _video[GBA_WIDTH * GBA_HEIGHT];

static void _silent_log(struct mLogger* l, int category,
                        enum mLogLevel level, const char* fmt, va_list args) {
    (void) l; (void) category; (void) level; (void) fmt; (void) args;
}

static struct mLogger _logger = {.log = _silent_log};

typedef struct {
    long frame;
    bool press;  // true = press, false = release
    int key;     // GBAKey enum value
} InputEvent;

typedef struct {
    InputEvent* items;
    size_t count;
    size_t cap;
} InputScript;

static int parse_button(const char* name) {
    static const struct {
        const char* name;
        int key;
    } map[] = {
        {"A", GBA_KEY_A},
        {"B", GBA_KEY_B},
        {"SELECT", GBA_KEY_SELECT},
        {"START", GBA_KEY_START},
        {"RIGHT", GBA_KEY_RIGHT},
        {"LEFT", GBA_KEY_LEFT},
        {"UP", GBA_KEY_UP},
        {"DOWN", GBA_KEY_DOWN},
        {"R", GBA_KEY_R},
        {"L", GBA_KEY_L},
    };
    for (size_t i = 0; i < sizeof(map) / sizeof(map[0]); ++i) {
        if (strcasecmp(name, map[i].name) == 0) return map[i].key;
    }
    return -1;
}

static const char* button_name(int key) {
    switch (key) {
        case GBA_KEY_A:      return "A";
        case GBA_KEY_B:      return "B";
        case GBA_KEY_SELECT: return "SELECT";
        case GBA_KEY_START:  return "START";
        case GBA_KEY_RIGHT:  return "RIGHT";
        case GBA_KEY_LEFT:   return "LEFT";
        case GBA_KEY_UP:     return "UP";
        case GBA_KEY_DOWN:   return "DOWN";
        case GBA_KEY_R:      return "R";
        case GBA_KEY_L:      return "L";
        default:             return "?";
    }
}

static bool script_push(InputScript* s, InputEvent ev) {
    if (s->count == s->cap) {
        size_t cap2 = s->cap ? s->cap * 2 : 16;
        InputEvent* tmp = realloc(s->items, cap2 * sizeof(*tmp));
        if (!tmp) return false;
        s->items = tmp;
        s->cap = cap2;
    }
    s->items[s->count++] = ev;
    return true;
}

static int cmp_events(const void* a, const void* b) {
    const InputEvent* ea = a;
    const InputEvent* eb = b;
    if (ea->frame != eb->frame) return (ea->frame < eb->frame) ? -1 : 1;
    // releases before presses on same frame so a "tap" (press+release same
    // frame) does not become a no-op
    if (ea->press != eb->press) return ea->press ? 1 : -1;
    return 0;
}

static bool load_input_script(const char* path, InputScript* out) {
    FILE* f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open input %s\n", path);
        return false;
    }
    char line[256];
    int lineno = 0;
    while (fgets(line, sizeof(line), f)) {
        ++lineno;
        // strip leading whitespace
        char* p = line;
        while (*p && isspace((unsigned char) *p)) ++p;
        if (!*p || *p == '#') continue;

        long frame;
        char op;
        char btn[32];
        int n = sscanf(p, "%ld %c %31s", &frame, &op, btn);
        if (n != 3 || (op != '+' && op != '-')) {
            fprintf(stderr, "input %s:%d: bad line: %s",
                    path, lineno, line);
            fclose(f);
            return false;
        }
        int key = parse_button(btn);
        if (key < 0) {
            fprintf(stderr, "input %s:%d: unknown button %s\n",
                    path, lineno, btn);
            fclose(f);
            return false;
        }
        InputEvent ev = {.frame = frame, .press = (op == '+'), .key = key};
        if (!script_push(out, ev)) {
            fprintf(stderr, "OOM building input script\n");
            fclose(f);
            return false;
        }
    }
    fclose(f);
    qsort(out->items, out->count, sizeof(*out->items), cmp_events);
    return true;
}

static bool load_cheats(struct mCore* core, const char* path) {
    struct mCheatDevice* device = core->cheatDevice(core);
    if (!device) {
        fprintf(stderr, "core has no cheat device\n");
        return false;
    }
    struct VFile* vf = VFileOpen(path, O_RDONLY);
    if (!vf) {
        fprintf(stderr, "cannot open cheats %s\n", path);
        return false;
    }
    mCheatDeviceClear(device);
    if (!mCheatParseFile(device, vf)) {
        fprintf(stderr, "mCheatParseFile failed for %s\n", path);
        vf->close(vf);
        return false;
    }
    vf->close(vf);
    size_t nsets = mCheatSetsSize(&device->cheats);
    size_t enabled = 0;
    for (size_t i = 0; i < nsets; ++i) {
        struct mCheatSet* set = *mCheatSetsGetPointer(&device->cheats, i);
        if (set->enabled) ++enabled;
    }
    fprintf(stderr, "cheats: %zu sets parsed, %zu enabled\n", nsets, enabled);
    return true;
}

static bool load_state(struct mCore* core, const char* path) {
    struct VFile* vf = VFileOpen(path, O_RDONLY);
    if (!vf) {
        fprintf(stderr, "cannot open state %s\n", path);
        return false;
    }
    bool ok = mCoreLoadStateNamed(core, vf, SAVESTATE_ALL);
    vf->close(vf);
    if (!ok) {
        fprintf(stderr, "mCoreLoadStateNamed failed for %s\n", path);
        return false;
    }
    fprintf(stderr, "state: loaded %s\n", path);
    return true;
}

static bool dump_ram(struct mCore* core, FILE* out) {
    const struct mCoreMemoryBlock* blocks = NULL;
    size_t nblocks = core->listMemoryBlocks(core, &blocks);
    fprintf(stderr, "dumping %zu memory blocks (writeable):\n", nblocks);
    for (size_t i = 0; i < nblocks; ++i) {
        if (!(blocks[i].flags & mCORE_MEMORY_WRITE)) continue;
        size_t size = 0;
        void* ptr = core->getMemoryBlock(core, blocks[i].id, &size);
        if (!ptr || size == 0) continue;
        fprintf(stderr, "  [%zu] id=0x%zx %-8s %zu bytes\n",
                i, (size_t) blocks[i].id, blocks[i].shortName, size);
        if (fwrite(ptr, 1, size, out) != size) {
            fprintf(stderr, "fwrite failed\n");
            return false;
        }
    }
    return true;
}

static void usage(const char* prog) {
    fprintf(stderr,
        "usage: %s --rom <rom.gba> [--frames N] [--input file] "
        "[--cheats file] [--state file] [--dump-ram out]\n", prog);
}

int main(int argc, char** argv) {
    const char* rom_path = NULL;
    const char* input_path = NULL;
    const char* cheats_path = NULL;
    const char* state_path = NULL;
    const char* dump_path = NULL;
    long frames = 1800;

    static struct option long_opts[] = {
        {"rom",      required_argument, 0, 'r'},
        {"frames",   required_argument, 0, 'f'},
        {"input",    required_argument, 0, 'i'},
        {"cheats",   required_argument, 0, 'c'},
        {"state",    required_argument, 0, 's'},
        {"dump-ram", required_argument, 0, 'd'},
        {"help",     no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };
    int opt;
    while ((opt = getopt_long(argc, argv, "r:f:i:c:s:d:h",
                              long_opts, NULL)) != -1) {
        switch (opt) {
            case 'r': rom_path = optarg; break;
            case 'f': frames = strtol(optarg, NULL, 10); break;
            case 'i': input_path = optarg; break;
            case 'c': cheats_path = optarg; break;
            case 's': state_path = optarg; break;
            case 'd': dump_path = optarg; break;
            case 'h': usage(argv[0]); return 0;
            default: usage(argv[0]); return 2;
        }
    }
    if (!rom_path || frames <= 0) {
        usage(argv[0]);
        return 2;
    }

    mLogSetDefaultLogger(&_logger);

    struct mCore* core = mCoreFind(rom_path);
    if (!core) {
        fprintf(stderr, "mCoreFind failed for %s\n", rom_path);
        return 1;
    }
    if (!core->init(core)) {
        fprintf(stderr, "core->init failed\n");
        return 1;
    }
    mCoreInitConfig(core, "gbaPlay");
    core->setVideoBuffer(core, _video, GBA_WIDTH);

    if (!mCoreLoadFile(core, rom_path)) {
        fprintf(stderr, "mCoreLoadFile failed\n");
        core->deinit(core);
        return 1;
    }
    core->reset(core);

    if (state_path && !load_state(core, state_path)) {
        core->deinit(core);
        return 1;
    }
    if (cheats_path && !load_cheats(core, cheats_path)) {
        core->deinit(core);
        return 1;
    }

    InputScript script = {0};
    if (input_path) {
        if (!load_input_script(input_path, &script)) {
            core->deinit(core);
            return 1;
        }
        fprintf(stderr, "input: %zu events from %s\n",
                script.count, input_path);
    }

    uint32_t keys = 0;
    size_t evi = 0;
    for (long frame = 0; frame < frames; ++frame) {
        // apply all events scheduled for this frame BEFORE running the frame
        while (evi < script.count && script.items[evi].frame == frame) {
            const InputEvent* ev = &script.items[evi];
            uint32_t mask = 1u << ev->key;
            if (ev->press) keys |= mask;
            else            keys &= ~mask;
            fprintf(stderr, "  frame %ld: %s %s -> 0x%03x\n",
                    frame, ev->press ? "press" : "release",
                    button_name(ev->key), keys);
            ++evi;
        }
        // warn if events scheduled in the past (sorted, so only on first miss)
        if (evi < script.count && script.items[evi].frame < frame) {
            fprintf(stderr, "warn: input event at frame %ld < current %ld "
                    "(unsorted?)\n", script.items[evi].frame, frame);
        }
        core->setKeys(core, keys);
        core->runFrame(core);
    }

    fprintf(stderr, "frames: %ld total\n", frames);

    FILE* out = stdout;
    if (dump_path) {
        out = fopen(dump_path, "wb");
        if (!out) {
            fprintf(stderr, "cannot open dump %s\n", dump_path);
            core->deinit(core);
            free(script.items);
            return 1;
        }
    }
    bool ok = dump_ram(core, out);
    if (dump_path) fclose(out);

    core->deinit(core);
    free(script.items);
    return ok ? 0 : 1;
}
