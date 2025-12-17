# 技術スタックと運用

## 基本技術
- 言語/ランタイム: Python 3.11+
- パッケージ管理: uv（ビルドは hatchling）
- 主要依存: anthropic (LLM API), jsonschema (スキーマ検証), pyyaml (設定), cryptography (署名検証), hypothesis/pytest (テスト), pydantic/pydantic-settings (設定検証)
- オプション依存: httpx (OpenAI/Gemini プロバイダ利用時に必要)
- 配布形態: `pyproject.toml` の scripts で `magi` を提供

## アーキテクチャ概要
- CLI レイヤー（`magi`）→ ConsensusEngine（Thinking/Debate/Voting）→ Agent/LLM/Context 管理 → Output/Plugins
- マルチプロバイダ対応 (ProviderConfigLoader): Anthropic, OpenAI, Gemini を抽象化し、設定ファイル/環境変数からロード。
- Core と Plugin を分離。合議フローは TokenBudgetManager → TemplateLoader → SchemaValidator → QuorumManager → StreamingEmitter でハードニング済み。
- GuardrailsAdapter を SecurityFilter 前段に挿入し、fail-open/fail-closed を設定で切替。遮断/失敗はイベントにコード付きで記録。
- ストリーミングは QueueStreamingEmitter でバッファリングし、ドロップ/TTFB/elapsed を計測しつつ fail-safe にフォールバック。
- セキュリティフィルタとプラグインガードで入力サニタイズ・メタ文字検証を実施。
- `BridgeAdapter` により外部 CLI 実行時の環境変数分離と stderr マスク（シークレット漏洩防止）を実現。
- `ConcurrencyController` により LLM/Plugin の同時実行数をセマフォ管理。
- spec_sync で `spec.json` と `tasks.md` を原子的に同期し、残タスクとメタ情報を一貫させる。

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
- SchemaValidator: ツール呼び出し JSON を jsonschema で検証し、再生成リトライとエラーロギングを行う。
- QuorumManager: エージェントごとの失敗/除外を追跡し、クオーラム未達時はフェイルセーフ応答へ遷移。
- StreamingEmitter: ストリーミング出力と再接続リトライ（MAGI_CLI_STREAM_RETRY_COUNT）、ドロップ計測と fail-safe イベント付与を実施。
- GuardrailsAdapter: 前段でプロンプト難読化や jailbreak を検知し、タイムアウト/例外は fail-open/closed ポリシーで処理。
- SecurityFilter/PluginGuard/PluginSignatureValidator: マーカー付与・制御文字エスケープ・禁止パターン検知・メタ文字拒否、プラグイン YAML を正規化した上で署名/ハッシュ検証。
- ConcurrencyController: `asyncio.Semaphore` を用いた同時実行数制御とタイムアウト、レートリミット計測。
- BridgeAdapter: 外部プロセス実行時の `MAGI_PROVIDER_*` 環境変数注入と、エラー出力からのシークレット自動マスク。
- PluginPermissionGuard: プラグインによるプロンプト上書きを `CONTEXT_ONLY` / `FULL_OVERRIDE` のスコープで制御し、署名信頼度と組み合わせて検証。

## 環境変数・設定

### マルチプロバイダ設定
プロバイダ ID (anthropic, openai, gemini) ごとに設定可能。
- `MAGI_<PROVIDER>_API_KEY`: API キー (例: `MAGI_OPENAI_API_KEY`)
- `MAGI_<PROVIDER>_MODEL`: 使用モデル
- `MAGI_<PROVIDER>_ENDPOINT`: API エンドポイント (OpenAI 互換 API などで使用)
- `MAGI_<PROVIDER>_OPTIONS`: プロバイダ固有オプション (JSON 文字列)
- `MAGI_DEFAULT_PROVIDER`: デフォルトで使用するプロバイダ ID (既定: `anthropic`)
- 従来互換: `MAGI_API_KEY`, `MAGI_MODEL` は `MAGI_DEFAULT_PROVIDER` (Anthropic) の設定として読み込まれます。

### 一般設定 (Pydantic V2 `MagiSettings` 対応)
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
- `CONSENSUS_STREAMING_ENABLED`: ストリーミング出力の有効化
- `CONSENSUS_STREAMING_QUEUE_SIZE` / `CONSENSUS_STREAMING_EMIT_TIMEOUT`: キュー長と送出タイムアウト
- `LOG_CONTEXT_REDUCTION_KEY`: 削減ログの出力可否フラグ
- `CONSENSUS_HARDENED_ENABLED`: ハードニング済みパスを有効化
- `CONSENSUS_LEGACY_FALLBACK`: フェイルセーフ時に旧実装へフォールバック
- `CONSENSUS_GUARDRAILS_ENABLED`: Guardrails の有効化
- `CONSENSUS_GUARDRAILS_TIMEOUT`: Guardrails タイムアウト秒数
- `CONSENSUS_GUARDRAILS_TIMEOUT_BEHAVIOR` / `CONSENSUS_GUARDRAILS_ERROR_POLICY`: fail-open / fail-closed ポリシー
- `MAGI_PLUGIN_PUBKEY_PATH`: プラグイン署名検証に用いる公開鍵パス
- `MAGI_PRODUCTION_MODE`: 本番モードフラグ（公開鍵設定を必須化）
- `MAGI_LLM_CONCURRENCY_LIMIT`: LLM 同時実行数制限
- `MAGI_PLUGIN_CONCURRENCY_LIMIT`: プラグイン同時実行数制限
- `MAGI_PLUGIN_LOAD_TIMEOUT`: プラグインロードタイムアウト
- `MAGI_PLUGIN_PROMPT_OVERRIDE_ALLOWED`: プラグインによるプロンプト完全上書きの許可
- `magi.yaml`: 上記設定をファイルで上書き可能。`providers` セクションで複数プロバイダを記述可能。

## ポート/サービス
- CLI ツールのため固定ポートなし。外部通信は設定された LLM プロバイダへの HTTPS のみ。

updated_at: 2025-12-18
