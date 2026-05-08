# gamehackbench/gba-base — mGBA 0.10.5 + gba_probe + gba_play, Debian bookworm.
# Goal: bit-exact GBA emulation in a portable container.

FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates cmake build-essential pkg-config \
    libpng-dev zlib1g-dev liblua5.4-dev \
 && rm -rf /var/lib/apt/lists/*

# mGBA 0.10.5, pinned.
RUN git clone --depth 1 --branch 0.10.5 https://github.com/mgba-emu/mgba.git /src
WORKDIR /src/build

RUN cmake .. \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DBUILD_ROM_TEST=ON \
    -DBUILD_QT=OFF -DBUILD_SDL=OFF \
    -DUSE_FFMPEG=OFF -DUSE_DISCORD_RPC=OFF \
    -DUSE_LIBZIP=OFF -DUSE_LZMA=OFF -DUSE_SQLITE3=OFF \
    -DBUILD_LIBRETRO=OFF -DBUILD_TEST=OFF -DBUILD_PERF=OFF \
 && make mgba mgba-rom-test -j"$(nproc)"

# Build gba_probe and gba_play with the same defines libmgba.so was compiled
# with. Mismatching defines = mismatched struct field offsets = silent ABI
# breakage at runtime.
COPY gba_probe.c /tools/gba_probe.c
COPY gba_play.c  /tools/gba_play.c
WORKDIR /tools
RUN cc -O2 -Wall -Wextra \
    -DM_CORE_GBA -DM_CORE_GB \
    -DUSE_DEBUGGERS -DUSE_GDB_STUB \
    -DENABLE_SCRIPTING -DUSE_LUA \
    -I/src/include \
    gba_probe.c \
    -L/src/build -lmgba \
    -Wl,-rpath,/usr/local/lib \
    -o /tools/gba_probe \
 && cc -O2 -Wall -Wextra \
    -DM_CORE_GBA -DM_CORE_GB \
    -DUSE_DEBUGGERS -DUSE_GDB_STUB \
    -DENABLE_SCRIPTING -DUSE_LUA \
    -I/src/include \
    gba_play.c \
    -L/src/build -lmgba \
    -Wl,-rpath,/usr/local/lib \
    -o /tools/gba_play


FROM debian:bookworm-slim AS runtime

# Runtime libs for the emulator + reverse-engineering toolkit baked into the
# base so every GBA task inherits the same disassembly stack:
#   - binutils-arm-none-eabi: objdump/readelf for ARM/THUMB
#   - python3-capstone: programmatic disasm (Capstone 5 ARM/THUMB backend)
#   - xxd / hexdump (bsdmainutils): byte spelunking utilities
# python3 itself is in here so per-task Dockerfile.default doesn't need to
# re-install it. radare2 omitted (not in bookworm-slim default repos);
# objdump + capstone cover both interactive and programmatic RE.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng16-16 zlib1g liblua5.4-0 \
    python3 python3-capstone \
    binutils-arm-none-eabi \
    bsdmainutils xxd \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/build/libmgba.so* /usr/local/lib/
COPY --from=builder /src/build/test/mgba-rom-test /usr/local/bin/mgba-rom-test
COPY --from=builder /tools/gba_probe /usr/local/bin/gba_probe
COPY --from=builder /tools/gba_play  /usr/local/bin/gba_play
RUN ldconfig

WORKDIR /work
ENTRYPOINT []
CMD ["gba_play", "--help"]
