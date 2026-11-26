# 変更履歴 (Changelog)

VoxMate の主な変更点・リリース内容を記録しています。

## [0.1.4] - 2026-11-26

AmiVoice API による音声認識バックエンド（`VOXMATE_STT=amivoice`）と開発・リリース規約（`CONTRIBUTING.md`）を追加したリリースです。

### 追加・改善

- **AmiVoice API 音声認識対応 (`stt_amivoice.py`, `server.py`, `.env.example`)**
  - 同期 HTTP インタフェース（`https://acp-api.amivoice.com/v1/nolog/recognize`）に対応した `transcribe_wav_amivoice()` を実装
  - `AMIVOICE_PROFILE_WORDS`（`表記 読み|表記 読み` 形式の URL エンコード）によるドメイン語彙・固有名詞登録に対応
  - ユニットテスト（`tests/test_amivoice_stt.py`）を追加
- **開発・リリースガイドライン (`CONTRIBUTING.md`, `README.md`, `README.en.md`)**
  - テスト実行、コミット規約、`pyproject.toml` / `CHANGELOG.md` / タグリリース手順をまとめた `CONTRIBUTING.md` を追加

## [0.1.3] - 2026-11-26

カスタムウェイクワード（`openWakeWord`）の導入、コンテキスト取得の高速化、公式 Gemini API バックエンドの追加、およびユニットテスト拡充を行ったリリースです。

### 追加・改善

- **低遅延カスタムウェイクワード KWS (`models/chotto_kiite.onnx`, `tools/kws_*.py`, `server.py`, `static/index.html`)**
  - 「ちょっと聞いて」を検知する軽量 `Conv1d` ONNX モデル（VOICEVOX 合成音声 2,000 件＋生声録音 `/kws` で学習）と `/ws/kws` 80ms 推論を追加し、約 0.2 秒でのウェイクワード起動に対応
- **応答速度・ハンズフリー体験の改善 (`server.py`, `static/index.html`)**
  - 日時コンテキストの事前注入、ツールパスの明示、カレンダー／Gmail のプリフェッチにより照会応答を高速化
  - ハンズフリー待機・文字起こし・処理中のステータス表示を整理し、再生後の不要な自動フォロートリガを無効化
- **公式 Gemini API バックエンド (`backends/gemini.py`, `backends/__init__.py`)**
  - `VOXMATE_BACKEND=gemini`（`GEMINI_API_KEY` / `GEMINI_MODEL`）による `streamGenerateContent?alt=sse` ストリーミング対応の `GeminiApiSession` を追加
  - `systemInstruction` によるキャラクター口調・表情タグ連携、マルチターン履歴保持（最大 40 メッセージ）、話者切替時・リセット時の履歴クリアに対応
  - `create_backend_session()` のディスパッチをマッピング化し、拡張しやすい構成へ整理
- **ユニットテストの拡充 (`tests/test_gemini_backend.py`, `tests/test_speech_helpers.py`)**
  - Gemini SSE パース・テキスト抽出・ファクトリ生成・API キー未設定ガードのテストを追加
  - `extract_expression_tag`・`clean_for_speech`・`_extract_lipsync_timeline` のユニットテストを追加
- **ドキュメント更新 (`.env.example`, `README.md`, `README.en.md`)**
  - `VOXMATE_BACKEND=gemini` と `GEMINI_API_KEY` / `GEMINI_MODEL` の設定手順を追記

## [0.1.2] - 2026-11-25

LLM による文ごとの表情・ポーズ指定、表情バリエーションの拡充、自然な待機・傾聴仕草、および VOICEVOX 音素データ連動の精密リップシンクを実装したリリースです。

### 追加・改善

- **LLM 表情タグ連動＆全12表情対応 (`server.py`, `static/index.html`, `tools/extract_portraits.py`)**
  - `happy` / `shy` / `surprised` / `troubled` / `angry` / `sad` / `pale` / `playful` / `speak` の9種を LLM が `[expr:...]` タグで文ごとに指定できるようにし、ローカル高速パスやタグ省略時はキーワード判定へ自動フォールバック
  - 全12キャラクターの衣装ネスト構造や固有パーツ（腕ポーズ、コバコの耳・外ハネ垂れ、東北イタコの後ろのおばけ、WhiteCUL のまばたき等）を網羅して再抽出
- **VOICEVOX 音素連動の「あ・い・う・え・お」＆全感情リップシンク (`server.py`, `static/index.html`)**
  - `audio_query` のモーラ・子音長から音素タイムラインを生成し、通常発話時は `speak_a`〜`speak_o` ↔ `idle` で5母音リップシンクを実現
  - 各感情表情にも口閉じ差分（`<表情>_c`）を用意し、表情や腕ポーズをチラつかせることなく全感情で口パクが動くよう対応
- **自然な立ち居振る舞い・感情別モーション (`static/index.html`)**
  - 考え中（`think`）の困り眉を解消し、録音中はわずかに傾いて耳を傾け、呼びかけ・ツール確認時に小さく頷くリアクションを追加
  - 感情に応じた控えめな CSS モーション（`anim-hop` / `anim-playful` / `anim-shy` / `anim-droop` / `anim-shake`）と待機中のランダム仕草を実装

## [0.1.1] - 2026-11-24

ハンズフリー会話時のウェイクワード体験の改善と、全12キャラクターの表情・腕ポーズバリエーション拡充を行ったアップデートです。

### 追加・改善

- **ウェイクワードモード＆ハイブリッド待機 (`static/index.html`, `server.py`)**
  - プリロールリングバッファと適応型 VAD によるウェイクワード検知を実装（選択中キャラクター名での呼びかけに対応）
  - ウェイクワードのみの呼びかけ時に起動チャイムを鳴らして受付状態へ遷移し、一息での連続発話と使い分けられるハイブリッド方式を導入
  - ウェイクワード未検出の環境音等では UI 通知やエラー表示を出さず、静かに待機状態を維持するよう修正
- **全12キャラクターの9表情・腕ポーズ対応 (`tools/extract_portraits.py`, `server.py`, `static/index.html`)**
  - 立ち絵 PSD から共通バウンディングボックス基準で9表情（`idle` / `blink` / `speak` / `think` / `happy` / `troubled` / `surprised` / `shy` / `angry`）を抽出する `tools/extract_portraits.py` を追加
  - AI の返答テキスト・アラーム／リマインダー発火・キャンセル操作に応じた感情連動の表情切替と発話後の余韻ホールドを実装
- **ドキュメント**
  - 英語版ドキュメント（`README.en.md`）および `README.md` との言語切替リンクを追加

## [0.1.0] - 2026-11-24

**VoxMate** の初回パブリックリリースです。ローカル Whisper による音声認識、決定論的ファストパス、差し替え可能な AI バックエンド、VOICEVOX 音声合成を統合したクロスプラットフォーム＆マルチデバイス対応のパーソナル音声アシスタントです。

### 追加・実装した主な機能

- **マルチデバイス対応 Web UI (`static/index.html`)**
  - PC（ワイド画面＋統合入力バー）、スマートフォン、Echo Show 5（`788×394` コンパクト操作UI）にそれぞれ最適化したレイアウトを搭載
  - キャラクター・話速・会話履歴・タイマー・アラーム停止状態を接続中の全端末でリアルタイム同期
  - 立ち絵の呼吸・まばたき・リップシンク・表情切替に対応（立ち絵未配置時はキャラクターカラーのプレースホルダーへ自動フォールバック）
  - テキスト送信・録音送信ともに紙飛行機アイコンへ統一し、初回起動・コンテクストクリア時は吹き出しなしのシンプルな空状態表示を採用
- **決定論的ファストパス (`fast_path.py`)**
  - 時刻・日付・曜日の確認、タイマー／アラーム操作、SwitchBot の単純 ON/OFF を LLM を経由せず 0 秒台で即実行・音声返答
  - キャラクター口調に合わせた自然な日本語語尾（丁寧語・ずんだもん・めたん・つむぎ等）とユニットテスト（`tests/test_fast_path.py`）を整備
- **タイマー・アラーム・音量分離 (`server.py`, `static/index.html`)**
  - 永続化対応のタイマー／リマインダー API（`/api/timers`, `/api/alerts/dismiss`）とバックグラウンド監視ループを実装
  - 「会話音量」と「アラーム音量」の独立スライダー（操作時の試し鳴らし機能付き）を搭載
  - リマインダー（会話音量で 1 回読み上げ）と目覚ましアラーム（アラーム音量でループ鳴動＋画面中央の大型「停止」モーダル・全端末連動停止）を分離
  - ヘッダーに動作中タイマーの残り時間バッジと VOICEVOX 未接続警告を表示
- **差し替え可能な AI バックエンド (`backends/`)**
  - 環境変数 `VOXMATE_BACKEND` により `agy`（Antigravity CLI 常駐セッション）と `claude`（Claude Code CLI）を切り替え可能
  - `VOXMATE_WORKDIR` 内の `VOXMATE.md`・`MEMORY.md`・`SOUL.md` を自動読み込みし、個人の記憶や秘書設定を別リポジトリへ安全に分離可能
- **クロスプラットフォーム対応 ＆ パフォーマンス改善**
  - `pyproject.toml` の環境マーカーにより、Apple Silicon macOS では `mlx-whisper`、Linux / Windows では `faster-whisper` を自動選択
  - 起動時の STT バックグラウンドウォームアップと短文 VOICEVOX TTS のインメモリキャッシュを導入
- **同梱ツール・テンプレート・ドキュメント**
  - 汎用 `sb`（SwitchBot API v1.1・ローカルキャッシュ付き）および `timer` CLI を `tools/` に同梱し、サーバー起動時に `PATH` へ自動追加
  - `.env.example`、`examples/VOXMATE.md`、`examples/secretary-ops-template.md`（カレンダー・メール・スマートホーム連携用）を整備
  - `README.md` にセットアップ手順・対応キャラクター丸アイコン一覧・マルチデバイススクショ・4 シーンデモ GIF を掲載
