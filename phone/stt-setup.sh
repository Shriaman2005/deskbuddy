#!/data/data/com.termux/files/usr/bin/bash
# Optional: offline dictation on the phone. Run in Termux:  bash ~/deskbuddy/stt-setup.sh
# Builds a pinned whisper.cpp (tag + commit checked) into ~/stt/whisper-cli, downloads two 8-bit models with pinned
# SHA-256 into ~/stt/models (the files dictation.py looks for), proves the build by transcribing whisper.cpp's own
# 11 s sample, then removes the source and the build tools it installed. Takes ~10 minutes and ~150 MB at the end.
# Safe to run again: a model that already matches its checksum is kept, a working ~/stt/whisper-cli is kept
# (FORCE=1 rebuilds it).
set -eu

TAG=v1.9.5
COMMIT=d1be6fde11ac6e0407606b4e42fe72d34add8037        # what the tag must point at (the laptop's build is this one)
REPO=https://github.com/ggml-org/whisper.cpp
HF=https://huggingface.co/ggerganov/whisper.cpp/resolve/main
# ggml-base-q8_0: the file the laptop uses; ggml-tiny-q8_0: Hugging Face's LFS checksum (x-linked-etag)
BASE_SHA=c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9
TINY_SHA=c2085835d3f50733e2ff6e4b41ae8a2b8d8110461e18821b09a15c40c42d1cca

STT=$HOME/stt
SRC=$HOME/.whisper-build
say() { echo "[stt-setup] $*"; }
die() { echo "[stt-setup] !! $*" >&2; exit 1; }
[ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ] || die "run this inside Termux"
mkdir -p "$STT/models"

# fetch NAME SHA: download a model unless the file there already has the right checksum
fetch() {
  local f=$STT/models/ggml-$1-q8_0.bin
  if [ -f "$f" ] && echo "$2  $f" | sha256sum -c --quiet 2>/dev/null; then say "ggml-$1-q8_0.bin already here and matches"; return; fi
  say "downloading ggml-$1-q8_0.bin"
  curl -fL --retry 3 -o "$f.part" "$HF/ggml-$1-q8_0.bin"
  echo "$2  $f.part" | sha256sum -c --quiet || { rm -f "$f.part"; die "ggml-$1-q8_0.bin does not match its checksum: deleted, nothing installed"; }
  mv "$f.part" "$f"
}

if [ -x "$STT/whisper-cli" ] && [ -z "${FORCE:-}" ]; then
  say "$STT/whisper-cli is already there (FORCE=1 to rebuild it)"
else
  [ "$(df -Pk "$HOME" | awk 'NR==2{print $4}')" -gt 1500000 ] || die "less than 1.5 GB free: the build needs room"
  export DEBIAN_FRONTEND=noninteractive
  NEW=()   # build tools this script adds: only these are removed again
  for p in git cmake clang make; do dpkg -s "$p" >/dev/null 2>&1 || NEW+=("$p"); done
  trap 'rm -rf "$SRC"' EXIT
  apt-get update
  apt-get -y install git cmake clang make libc++   # libc++ stays: the binary needs it
  rm -rf "$SRC"
  say "cloning whisper.cpp $TAG"
  git clone --quiet --depth 1 --branch "$TAG" "$REPO" "$SRC"
  [ "$(git -C "$SRC" rev-parse HEAD)" = "$COMMIT" ] || die "$TAG does not point at the pinned commit: not building"
  say "building (a few minutes, the phone gets warm)"
  cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_OPENMP=OFF \
    -DWHISPER_BUILD_TESTS=OFF >"$SRC/cmake.log" 2>&1 || { tail -20 "$SRC/cmake.log"; die "cmake failed"; }
  cmake --build "$SRC/build" --target whisper-cli -j2 || die "build failed"
  cp "$SRC/build/bin/whisper-cli" "$STT/whisper-cli.new"
  chmod +x "$STT/whisper-cli.new"

  fetch tiny "$TINY_SHA"
  say "test: transcribing whisper.cpp's own sample with the tiny model"
  OUT=$("$STT/whisper-cli.new" -m "$STT/models/ggml-tiny-q8_0.bin" -f "$SRC/samples/jfk.wav" -nt -np -t 4 2>/dev/null) \
    || { rm -f "$STT/whisper-cli.new"; die "the new whisper-cli crashed on this phone (illegal instruction?): not installed"; }
  echo "$OUT"
  echo "$OUT" | grep -qi "country" || { rm -f "$STT/whisper-cli.new"; die "unexpected text from the test clip: not installed"; }
  mv -f "$STT/whisper-cli.new" "$STT/whisper-cli"

  rm -rf "$SRC"
  if [ ${#NEW[@]} -gt 0 ]; then say "removing the build tools: ${NEW[*]}"; apt-get -y remove --purge "${NEW[@]}" || true; fi
fi
fetch tiny "$TINY_SHA"
fetch base "$BASE_SHA"
say "done: $(du -sh "$STT" | cut -f1) in $STT. In the dashboard set 'Speech model runs on' to Phone."
