# 技術スタックと運用

## 基本技術
- 言語/ランタイム: Python 3.11+
- パッケージ管理: uv（ビルドは hatchling）
- 主要依存: anthropic (LLM API), pyyaml (設定), hypothesis/pytest (テスト)
- 配布形態: `pyproject.toml` の scripts で `magi` を提供

## アーキテクチャ概要
- CLI レイヤー（`magi`）→ ConsensusEngine（Thinking/Debate/Voting）→ Agent/LLM/Context 管理 → Output/Plugins
- Core と Plugin を分離。合議フローは TokenBudgetManager → TemplateLoader → SchemaValidator → QuorumManager → StreamingEmitter でハードニング済み。
- セキュリティフィルタとプラグインガードで入力サニタイズ・メタ文字検証を実施。

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

## 合議ハードニング機能
- TokenBudgetManager: 言語別トークン推定と重要度圧縮で CONSENSUS_TOKEN_BUDGET を維持。
- TemplateLoader: YAML/JSON/Jinja2 テンプレートを TTL キャッシュし、force reload/ホットリロード対応。
- SchemaValidator: ツール呼び出し JSON をスキーマ検証し、再生成リトライとエラーロギングを行う。
- QuorumManager: エージェントごとの失敗/除外を追跡し、クオーラム未達時はフェイルセーフ応答へ遷移。
- StreamingEmitter: ストリーミング出力と再接続リトライ（MAGI_CLI_STREAM_RETRY_COUNT）を実施。
- SecurityFilter/PluginGuard: マーカー付与・制御文字エスケープ・禁止パターン検知・署名/ハッシュ検証。

## 環境変数・設定
- `MAGI_API_KEY` (必須): Anthropic API キー
- `MAGI_MODEL`: 使用モデル（既定 `claude-sonnet-4-20250514`）
- `MAGI_DEBATE_ROUNDS`: Debate ラウンド数（既定 1）
- `MAGI_VOTING_THRESHOLD`: `majority` / `unanimous`
- `MAGI_OUTPUT_FORMAT`: `json` / `markdown`
- `MAGI_TIMEOUT`: API タイムアウト秒数
- `MAGI_RETRY_COUNT`: LLM 呼び出しリトライ上限
- `CONSENSUS_TOKEN_BUDGET`: 合議フェーズの最大トークン数
- `CONSENSUS_SUMMARY_RETRY_COUNT`: スキーマ再生成リトライ回数
- `CONSENSUS_TEMPLATE_TTL_SECONDS`: テンプレートキャッシュ TTL
- `CONSENSUS_VOTE_TEMPLATE`: 投票テンプレート名
- `CONSENSUS_TEMPLATE_BASE_PATH`: テンプレートディレクトリ
- `CONSENSUS_QUORUM_THRESHOLD`: クオーラム閾値
- `MAGI_CLI_STREAM_RETRY_COUNT`: ストリーミング再接続回数
- `LOG_CONTEXT_REDUCTION_KEY`: 削減ログの出力可否フラグ
- `CONSENSUS_HARDENED_ENABLED`: ハードニング済みパスを有効化
- `CONSENSUS_LEGACY_FALLBACK`: フェイルセーフ時に旧実装へフォールバック
- `magi.yaml`: 上記設定をファイルで上書き可能

## ポート/サービス
- CLI ツールのため固定ポートなし。外部通信は Anthropic API への HTTPS のみ。
