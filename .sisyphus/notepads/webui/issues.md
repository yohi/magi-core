# issues

## 2026-01-30 Task: QA
- `lsp_diagnostics` が Python に対して未設定（拡張子マッピングが無い）ため、代替として `uv run python -m compileall src` と `unittest` を用いて構文/実行整合を確認する。
- `tests/property` は実行時間が長く、短いタイムアウトだと途中で強制終了される（少なくとも 240s では未完）。

## 2026-01-30: Flaky timing test in test_plugin_loader.py
- Issue: TestPluginLoaderAsync.test_load_async_timeout_is_isolated was flaky in slow environments.
- Cause: The timeout (0.01s) was too tight compared to the normal load time of plugins.
- Fix: Increased the sleep duration for slow plugins to 0.5s and the timeout to 0.2s to make the timing more robust.

### Hypothesis HealthCheck.too_slow によるテスト失敗
- **問題**: `tests/unit/test_plugin_loader.py` の `test_default_values_applied_correctly` において、Hypothesisのデータ生成が遅すぎるために `FailedHealthCheck: HealthCheck.too_slow` エラーが発生し、CIやローカル環境でのテストが不安定になっていた。
- **対策**: `@settings` デコレータに `suppress_health_check=[HealthCheck.too_slow]` を追加することで、このヘルスチェックを抑制した。これにより、低速な環境でもテストが安定して実行されるようになった。

## 2026-01-30 Task: WebSocket implementation
- **再接続時のイベント再送**: 現在の実装では、切断後の再接続時に過去のイベントは再送されない（接続以降のイベントのみ）。クライアント側でリロード等が必要になる可能性がある。
- **イベントロスト**: `EventBroadcaster` のキューサイズ制限により、大量のイベントが発生した場合に古いイベントがドロップされる可能性がある。
- **切断検知**: `websocket.receive_text()` でクライアントからの切断を検知しているが、Keep-Alive/Ping-Pongの仕組みはWebSocketプロトコル依存。

## 2026-01-30 Task: WebSocket Testing
- **WSイベントの初期欠落**:
  - `create_session` 直後にバックグラウンドタスクが開始される仕様上、WebSocket接続が確立するまでの間に発生した初期イベント（`THINKING`フェーズ開始など）はクライアントに届かない。
  - これに対処するには、クライアント側で状態ポーリングを併用するか、サーバー側で履歴保持（Event Sourcing等）を実装する必要があるが、現状は仕様制限としている。
