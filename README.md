# VoxDesk

Echo Show 5 などの小型ディスプレイ向けに最適化された、VOICEVOX × mlx-whisper × `agy` 連携の音声対話 Web アプリケーションです。

## 構成

- **STT**: `mlx-whisper` (`mlx-community/whisper-large-v3-turbo-q4`)
- **LLM**: `agy` (`--input-format stream-json` 常駐セッション)
- **TTS**: VOICEVOX Engine (`http://127.0.0.1:50021`)
- **UI**: 左ペイン会話テキスト + 右ペイン立ち絵リップシンク（`788x394` / `960x480` 最適化）

## セットアップ（ローカル素材・バイナリの配置）

パブリックリポジトリには再配布不可の立ち絵画像や大容量の VOICEVOX Engine 本体は含めていません。利用前に以下を配置してください。

1. `voicevox/macos-arm64/` に VOICEVOX Engine を配置
2. `static/portraits/` に各キャラクター立ち絵・アイコン PNG（`<asset>_{idle,speak,blink,happy,think,icon}.png`）を配置
3. 依存パッケージを同期して起動:

```bash
uv sync
./start.sh
```
