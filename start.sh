#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/etc/profiles/per-user/${USER:-$(whoami)}/bin:/nix/var/nix/profiles/default/bin:${HOME}/.local/bin:/Applications/Orca.app/Contents/Resources/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# VOICEVOX Engine をクリーンに起動（再起動時のレース防止）
pkill -f "voicevox/macos-arm64/run" 2>/dev/null || true
sleep 0.5
echo "Starting VOICEVOX Engine..."
xattr -dr com.apple.quarantine "$DIR/voicevox/macos-arm64" 2>/dev/null || true
"$DIR/voicevox/macos-arm64/run" --host 127.0.0.1 --port 50021 > "$DIR/voicevox.log" 2>&1 &
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:50021/version >/dev/null 2>&1; then
    echo "VOICEVOX Engine ready!"
    break
  fi
  sleep 1
done

# adb の実体パスを起動時に1回だけ解決し、15秒おきに adb reverse を維持
ADB_BIN="$(command -v adb || nix shell nixpkgs#android-tools -c which adb 2>/dev/null || true)"
run_adb_reverse() {
  if [ -n "$ADB_BIN" ] && [ -x "$ADB_BIN" ]; then
    "$ADB_BIN" reverse tcp:8000 tcp:8000 >/dev/null 2>&1 || true
  fi
}

run_adb_reverse
(
  while true; do
    sleep 15
    run_adb_reverse
  done
) &
ADB_LOOP_PID=$!

cleanup() {
  kill "$ADB_LOOP_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting VoxMate server on http://127.0.0.1:8000 ..."
exec uv run python -m uvicorn server:app --host 127.0.0.1 --port 8000
