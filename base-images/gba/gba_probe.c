// gba_probe: load GBA ROM (optionally with cheats), run N frames, dump RW memory to stdout.
// Usage: gba_probe <rom.gba> <frames> [cheats.cht]

#include <mgba/core/cheats.h>
#include <mgba/core/config.h>
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba-util/common.h>
#include <mgba-util/vfs.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GBA_WIDTH 240
#define GBA_HEIGHT 160

static color_t _video[GBA_WIDTH * GBA_HEIGHT];

int main(int argc, char** argv) {
    if (argc < 3 || argc > 4) {
        fprintf(stderr, "usage: %s <rom.gba> <frames> [cheats.cht]\n", argv[0]);
        return 2;
    }

    const char* rom_path = argv[1];
    long frames = strtol(argv[2], NULL, 10);
    const char* cheats_path = (argc == 4) ? argv[3] : NULL;
    if (frames <= 0) {
        fprintf(stderr, "frames must be > 0\n");
        return 2;
    }

    mLogSetDefaultLogger(NULL);

    struct mCore* core = mCoreFind(rom_path);
    if (!core) {
        fprintf(stderr, "mCoreFind failed for %s\n", rom_path);
        return 1;
    }
    if (!core->init(core)) {
        fprintf(stderr, "core->init failed\n");
        return 1;
    }

    mCoreInitConfig(core, "gbaProbe");
    core->setVideoBuffer(core, _video, GBA_WIDTH);

    if (!mCoreLoadFile(core, rom_path)) {
        fprintf(stderr, "mCoreLoadFile failed\n");
        core->deinit(core);
        return 1;
    }

    core->reset(core);

    if (cheats_path) {
        struct mCheatDevice* device = core->cheatDevice(core);
        if (!device) {
            fprintf(stderr, "core has no cheat device\n");
            core->deinit(core);
            return 1;
        }
        struct VFile* vf = VFileOpen(cheats_path, O_RDONLY);
        if (!vf) {
            fprintf(stderr, "cannot open %s\n", cheats_path);
            core->deinit(core);
            return 1;
        }
        mCheatDeviceClear(device);
        if (!mCheatParseFile(device, vf)) {
            fprintf(stderr, "mCheatParseFile failed for %s\n", cheats_path);
            vf->close(vf);
            core->deinit(core);
            return 1;
        }
        vf->close(vf);
        size_t nsets = mCheatSetsSize(&device->cheats);
        size_t enabled = 0;
        for (size_t i = 0; i < nsets; ++i) {
            struct mCheatSet* set = *mCheatSetsGetPointer(&device->cheats, i);
            if (set->enabled) ++enabled;
        }
        fprintf(stderr, "cheats: %zu sets parsed, %zu enabled\n", nsets, enabled);
    }

    for (long i = 0; i < frames; ++i) {
        core->runFrame(core);
    }

    const struct mCoreMemoryBlock* blocks = NULL;
    size_t nblocks = core->listMemoryBlocks(core, &blocks);
    fprintf(stderr, "frames: %ld, dumping %zu memory blocks:\n", frames, nblocks);

    for (size_t i = 0; i < nblocks; ++i) {
        if (!(blocks[i].flags & mCORE_MEMORY_WRITE)) continue;
        size_t size = 0;
        void* ptr = core->getMemoryBlock(core, blocks[i].id, &size);
        if (!ptr || size == 0) continue;
        fprintf(stderr, "  [%zu] id=0x%zx %-8s %zu bytes\n",
                i, (size_t) blocks[i].id, blocks[i].shortName, size);
        if (fwrite(ptr, 1, size, stdout) != size) {
            fprintf(stderr, "fwrite failed\n");
            core->deinit(core);
            return 1;
        }
    }

    core->deinit(core);
    return 0;
}
