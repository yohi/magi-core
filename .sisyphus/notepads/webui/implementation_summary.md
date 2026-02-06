# WebUI Implementation Summary

## 概要
`webui-spec.md` に準拠するため、以下の修正を行いました。

## 実施項目

### 1. インフラ構成 (P0)
- `compose.yaml`: `magi-backend` の外部ポート公開を廃止し、`magi-frontend` (Nginx) 経由のみとしました。
- `magi-frontend` はホスト `3000:80` で公開されます。

### 2. REST API / WebSocket (P1)
- `POST /api/sessions`: レスポンスステータスを `"QUEUED"` に変更。Promptバリデーション (1-8000文字) を追加。
- `POST /api/sessions/{id}/cancel`: レスポンスステータスを `"CANCELLED"` に変更。
- WebSocket Error: `code` フィールド (`MAGI_CORE_ERROR`, `TIMEOUT`, `CANCELLED`, `INTERNAL`) を付与。

### 3. オプション・設定 (P2)
- **タイムアウト**: `SessionOptions.timeout_sec` が実行時に適用され、超過時に `TIMEOUT` エラーを送信します。
- **モデル選択**: フロントエンドからの `options.model` が `ConsensusEngine` に反映されます。
- **環境変数**: `MAX_CONCURRENCY`, `SESSION_TTL_SEC`, `CORS_ORIGINS` が `.env` から読み込まれます。

### 4. 運用・UX (P3)
- **TTLクリーンアップ**: バックグラウンドタスクによる定期的な期限切れセッション削除を実装しました。
- **Cancelボタン**: フロントエンドに「CANCEL」ボタンを追加し、途中停止とステータス表示 (`中止`) を実装しました。

## テスト結果
- 単体テスト: すべてパス (`tests/unit/test_webui_*.py`)
- 統合テスト: すべてパス (`tests/integration/test_webui_e2e.py` の回帰修正済み)

## 今後の推奨事項
- 本番運用時は `CORS_ORIGINS` を空にするか、信頼できるオリジンのみに制限してください。
- ログ出力設定 (`logging.conf` 等) を環境に合わせて調整してください。
