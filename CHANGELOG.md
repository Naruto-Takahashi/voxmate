# Changelog

All notable changes to VoxMate will be documented in this file.

## [0.1.0] - 2026-11-24

Initial public release of **VoxMate** — a cross-platform, multi-device personal voice assistant powered by local Whisper STT, deterministic fast-path routing, pluggable AI backends, and VOICEVOX.

### Added
- **Multi-Device Web UI (`static/index.html`)**
  - Responsive layouts for PC (wide pane + integrated input bar), smartphones, and Echo Show 5 (`788×394` compact floating controls).
  - Real-time state synchronization across devices (active character, speed, conversation history, timers, and alarm dismissal).
  - Live character portraits with breathing, blinking, lip-sync, expression switching, and fallback placeholders when portrait assets are not installed.
  - Minimal empty-state UI on initial launch and after context reset.
- **Deterministic Fast-Path (`fast_path.py`)**
  - Sub-second responses without invoking an LLM for clock/date queries, timer/alarm management, and SwitchBot simple ON/OFF commands.
  - Character-matched polite/casual Japanese endings and unit tests (`tests/test_fast_path.py`).
- **Timer, Alarm & Volume Separation (`server.py`, `static/index.html`)**
  - Persistent timer/reminder API (`/api/timers`, `/api/alerts/dismiss`) with background watcher.
  - Independent **Conversation Volume** and **Alarm Volume** sliders with audio preview on change.
  - Differentiated playback between one-shot reminders (`reminder`) and looping wake-up alarms (`alarm`) with a large center stop modal synced across all connected devices.
- **Pluggable AI Backends (`backends/`)**
  - Unified backend interface selectable via `VOXMATE_BACKEND` (`agy` for persistent Antigravity CLI, `claude` for Claude Code CLI).
  - Dynamic workspace prompt loading (`VOXMATE.md` and `MEMORY.md` inside `VOXMATE_WORKDIR`).
- **Cross-Platform STT & Performance**
  - Automatic dependency selection in `pyproject.toml`: `mlx-whisper` on Apple Silicon macOS, `faster-whisper` on Linux/Windows.
  - Background STT model warmup on startup and in-memory VOICEVOX TTS caching for short phrases.
- **Bundled Tools & Templates (`tools/`, `examples/`)**
  - Generic `sb` (SwitchBot API v1.1 with local device cache) and `timer` CLIs added automatically to `PATH`.
  - `.env.example`, `examples/VOXMATE.md`, and `examples/secretary-ops-template.md` for calendar, mail, timer, and smart home setup.
  - Complete `README.md` with setup guides, circular character icon table, screenshots, and animated demo GIF.
