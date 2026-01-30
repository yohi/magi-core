## WebUI Backend 実装計画（magi-core 内）

目的: `webui-spec.md` のバックエンド（FastAPI + REST/WS + セッション管理）を、このリポジトリに最小実装として追加する。

前提:
- 仕様: `webui-spec.md`
- 依存管理: `uv`
- テスト: `unittest`
- 出力/ドキュメント/コメント: 日本語

### タスク

- [ ] 1. FastAPI バックエンド骨格を追加（/api/health, /api/sessions, /api/sessions/{id}/cancel, /ws/sessions/{id}）
- [ ] 2. SessionManager を実装（同時数制限、TTL、状態保持、キャンセル）
- [ ] 3. MagiAdapter を実装（まずは MockAdapter、次に `ConsensusEngine` 直呼び）
- [ ] 4. EventBroadcaster を実装（10Hz目安、バックプレッシャ時の間引き、schema_version=1.0 付与）
- [ ] 5. unittest を追加（SessionManager 状態遷移、TTL、キャンセル、イベント整形）
- [ ] 6. プロジェクトレベル検証（LSP error 0、`uv run python -m compileall src`、`uv run python -m unittest discover -s tests -v`）
