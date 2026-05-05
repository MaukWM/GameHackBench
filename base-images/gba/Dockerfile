# gamehackbench/gba-base — mGBA 0.10.5 + gba_probe, Debian bookworm.
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

# Build gba_probe with same defines libmgba.so was compiled with.
COPY gba_probe.c /probe/gba_probe.c
WORKDIR /probe
RUN cc -O2 -Wall -Wextra \
    -DM_CORE_GBA -DM_CORE_GB \
    -DUSE_DEBUGGERS -DUSE_GDB_STUB \
    -DENABLE_SCRIPTING -DUSE_LUA \
    -I/src/include \
    gba_probe.c \
    -L/src/build -lmgba \
    -Wl,-rpath,/usr/local/lib \
    -o /probe/gba_probe


FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng16-16 zlib1g liblua5.4-0 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/build/libmgba.so* /usr/local/lib/
COPY --from=builder /src/build/test/mgba-rom-test /usr/local/bin/mgba-rom-test
COPY --from=builder /probe/gba_probe /usr/local/bin/gba_probe
RUN ldconfig

WORKDIR /work
ENTRYPOINT []
CMD ["gba_probe"]
