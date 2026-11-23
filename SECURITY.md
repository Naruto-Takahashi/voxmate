# Security Policy

## Supported Versions

現在はプレリリース（`v0.1.0-alpha.1` 以降の `main` ブランチ）のみサポート対象です。

| Version | Supported |
| ------- | --------- |
| `main` (`0.1.x`) | :white_check_mark: |

## Reporting a Vulnerability

セキュリティ上の脆弱性を発見した場合は、公開 Issue には詳細を書かず、以下のいずれかの方法で報告してください。

- **GitHub Private Vulnerability Reporting**: リポジトリの **Security** タブ → **Report a vulnerability**
- **メール連絡**: `t.naruto7610@gmail.com`

確認後、可能な限り速やかに調査および修正対応を行います。

## 運用上の注意

- VoxDesk はローカルネットワーク内（`127.0.0.1:8000` / USB `adb reverse`）での利用を想定しています。認証機構を持たないため、インターネットや信頼できない LAN へ直接公開しないでください。
- 音声ファイルや会話ログはローカルの `agy` セッションおよび VOICEVOX Engine でのみ処理されます。
