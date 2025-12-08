# 技術スタックと運用

## 基本技術
- 言語/ランタイム: Python 3.11+
- パッケージ管理: uv（ビルドは hatchling）
- 主要依存: anthropic (LLM API), pyyaml (設定), hypothesis/pytest (テスト)
- 配布形態: `pyproject.toml` の scripts で `magi` を提供

## アーキテクチャ概要
- CLI レイヤー（`magi`）→ Core エンジン（合議フェーズ）→ Agent/LLM/Context 管理 → Output/Plugins
- Core と Plugin を分離し、コマンド実行は CLI から orchestrate される。

## 開発環境
- uv で依存管理: `uv sync`
- 仮想環境は uv が自動生成（`.venv`）。
- hatchling でビルド。特別なフックなし。

## 主要コマンド
```bash
# セットアップ
uv sync

# 動作確認
uv run magi --help
uv run magi --version

# テスト（用途別）
uv run python -m unittest discover -s tests -v
uv run python -m unittest discover -s tests/unit -v
uv run python -m unittest discover -s tests/property -v
uv run python -m unittest discover -s tests/integration -v

# カバレッジ
uv run coverage run -m unittest discover -s tests
uv run coverage report
uv run coverage html
```

## 環境変数・設定
- `MAGI_API_KEY` (必須): Anthropic API キー
- `MAGI_MODEL`: 使用モデル（既定 `claude-sonnet-4-20250514`）
- `MAGI_DEBATE_ROUNDS`: Debate ラウンド数（既定 1）
- `MAGI_VOTING_THRESHOLD`: `majority`/`unanimous`
- `MAGI_TIMEOUT`: 秒数（既定 60）
- `magi.yaml`: モデル・ラウンド数・閾値・出力形式などを上書き可能

## ポート/サービス
- CLI ツールのため固定ポートなし。外部通信は Anthropic API への HTTPS のみ。
