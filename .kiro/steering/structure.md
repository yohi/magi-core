# プロジェクト構造

## ルート構成（抜粋）
```text
magi-core/
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
- `cli/`: 引数パーサーと CLI 起動
- `config/`: ConfigManager
- `llm/`: LLM クライアント
- `output/`: フォーマッタ
- `plugins/`: PluginLoader/CommandExecutor
- 共通モデル・エラーはルート直下の `models.py`/`errors.py`

## コード/命名規約
- src レイアウト。インポートは `magi.` プレフィックスで統一。
- コメント・docstring は日本語。Google Style に沿った記述を推奨。
- テストは unittest discover が前提。ディレクトリで対象を分割（unit/property/integration）。

## 補足
- プロジェクト設定や追加仕様は README と `.kiro/specs/` を参照。
