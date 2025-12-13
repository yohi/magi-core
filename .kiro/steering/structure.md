# プロジェクト構造

## ルート構成（抜粋）
```text
magi-core/
├── .kiro/             # ステアリング・spec ドキュメント
├── src/magi/           # アプリ本体（CLI/Core/Agents/Plugins など）
├── tests/              # unit/property/integration テスト
├── plugins/            # 追加プラグイン（例: magi-cc-sdd-plugin）
├── docs/               # ドキュメント
├── pyproject.toml      # パッケージ/ビルド設定
└── README.md
```

## src/magi 配下
- `__main__.py`: CLI エントリーポイント (`magi` script)
- `agents/`: ペルソナ・エージェント実装
- `core/`: 合議エンジン、コンテキスト管理
  - `consensus.py`: 合議フロー制御
  - `context.py`: コンテキスト/ログ管理
  - `streaming.py`: QueueStreamingEmitter でストリーミングをバッファリングし、TTFB/ドロップを記録した上で fail-safe にフォールバック
  - `token_budget.py`: TokenBudgetManager（要約・圧縮・削減ログ）
  - `template_loader.py`: テンプレート外部化・TTLキャッシュ・ホットリロード
  - `schema_validator.py`: ツール呼び出し JSON スキーマ検証
  - `quorum.py`: クオーラム・リトライ・フェイルセーフ判定
  - `spec_sync.py`: `spec.json` と `tasks.md` の整合同期（バックアップ+atomic write）
  - `providers.py`: プロバイダ共通コンテキスト定義
- `cli/`: 引数パーサーと CLI 起動
- `config/`: 設定管理
  - `manager.py`: ConfigManager。env/config マッピングとバリデーション。Guardrails/Streaming/署名キーフラグなども管理。
  - `provider.py`: ProviderConfigLoader。マルチプロバイダ設定（Anthropic/OpenAI/Gemini）のロードとマスク処理を担当。
- `llm/`: LLM 通信レイヤー
  - `client.py`: LLMClient。共通インターフェース定義。
  - `providers.py`: 各社（AnthropicAdapter, OpenAIAdapter, GeminiAdapter）のアダプタ実装。httpx の遅延ロードやヘルスチェックを含む。
- `output/`: フォーマッタ/ストリーミング出力
- `plugins/`: PluginLoader/CommandExecutor/PluginGuard（`loader.py` / `executor.py` / `guard.py`）
- `plugins/signature.py`: YAML を正規化して RSA/ECDSA 署名または sha256 ハッシュを検証（公開鍵は public_key_path > config.plugin_public_key_path > `MAGI_PLUGIN_PUBKEY_PATH` > `plugins/public_key.pem` の順で解決）
- `security/`: SecurityFilter（`filter.py` でサニタイズ・禁止パターン検知）
- `security/guardrails.py`: GuardrailsAdapter で前段チェックし、タイムアウト/例外はポリシーに応じて fail-open/closed かイベント記録
- 共通モデル・エラーはルート直下の `models.py` / `errors.py`

## .kiro 配下
- `.kiro/steering/`: プロダクト/技術/構造のステアリング文書
- `.kiro/specs/`: 各機能の requirements/design/tasks/spec.json 管理

## コード/命名規約
- src レイアウト。インポートは `magi.` プレフィックスで統一。
- コメント・docstring は日本語。Google Style に沿った記述を推奨。
- テストは unittest discover が前提。ディレクトリで対象を分割（unit/property/integration）。

## 補足
- プロジェクト設定や追加仕様は README と `.kiro/specs/` を参照。

updated_at: 2025-12-13