# Contributing to VoxMate

VoxMate へのコントリビューション・開発・リリース手順のルールです。

## 開発・テスト

変更を加えた場合は、コミット前に構文チェックとユニットテストがすべて通ることを確認してください。

```bash
uv run python -m py_compile server.py fast_path.py stt_amivoice.py backends/*.py
uv run python -m unittest discover -s tests -v
```

## コミット規約

- コミットメッセージは `type(scope): 説明` 形式（例: `feat(stt): ...`, `fix(backends): ...`, `docs(changelog): ...`）とします。
- フック等で絵文字が付与される環境では、メッセージ先頭に手動で絵文字を入れないでください。
- 機密情報（`.env`、API キー）、個人情報、再配布不可の立ち絵素材（PSD/PNG）や大容量モデルは絶対にコミットしないでください。

## リリース手順（バージョン更新・CHANGELOG・タグ）

機能追加や修正をリリースする際は、毎回以下の手順をセットで実施します。

1. `pyproject.toml` の `version` を新バージョン（例: `"0.1.4"`）へ更新する。
2. `CHANGELOG.md` の先頭に `## [X.Y.Z] - YYYY-MM-DD` セクションを追記し、主な変更点を記載する。
3. 上記の変更とテスト通過を確認してコミットする。
4. 注釈付きタグを作成して `main` とタグをプッシュする。
5. GitHub Release を作成する（`CHANGELOG.md` の該当セクションをリリースノートとして添付）。

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z: <概要>"
git push origin main --tags
gh release create vX.Y.Z --title "VoxMate vX.Y.Z" --notes "<CHANGELOG該当内容>"
```
