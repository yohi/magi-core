
## 2026-01-30 Task: EventBroadcaster 実装
- **Backpressure Strategy**:
  - `asyncio.Queue(maxsize=N)` を使用。
  - `publish` 時に `queue.full()` の場合、`queue.get_nowait()` で最古のイベントを破棄してから新しいイベントを `put_nowait()` する "Drop-Oldest" 戦略を採用。
  - これにより、遅いクライアントは中間状態を失うが、最終的な最新状態（またはそれに近い状態）を受け取ることができる。UI更新用途に適している。
- **Concurrency**:
  - `subscribe/unsubscribe` は `asyncio.Lock` で保護。
  - `publish` 時はロック内でリストのコピーを作成し、ロック外（あるいはロック内だが安全に）で反復処理を行うことで、反復中のリスト変更（unsubscription）による `RuntimeError` を回避。

## 2026-01-30 Task: SessionManager Wiring
- **Architecture**:
  - `SessionManager` wiring with `MagiAdapter` and `EventBroadcaster` allows for decoupled execution and real-time updates.
  - `MockMagiAdapter` is useful for testing without real LLM backend.
  - `EventBroadcaster`'s backpressure (drop-oldest) is important for preventing slow clients from blocking the backend.
  - Dependency injection in `SessionManager` makes testing easier.
- **Testing**:
  - Testing `SessionManager` requires careful handling of asynchronous task execution and event subscription timing. Using `MockMagiAdapter` with `asyncio.sleep` helps in verifying state transitions.

## 2026-01-30 Task: WebSocket implementation
- **WebSocket Pattern**:
  - `EventBroadcaster` を利用したPub/Subモデルを採用。
  - `asyncio.Queue` を介してイベントを受け渡し、FastAPIの `WebSocket` で送信。
  - 送信ループ (`queue.get()`) と受信ループ (`receive_text()`) を `asyncio.create_task` で並行実行し、`asyncio.wait(FIRST_COMPLETED)` でどちらかの終了（完了または切断）を待つパターンが有効。
  - `finally` ブロックで `unsubscribe` と `cancel_session` を確実に実行することでリソースリークを防ぐ。

## 2026-01-30 Task: WebSocket Testing
- **WSテストとTestClient**:
  - FastAPI/Starletteの `TestClient` は同期コンテキストで動作するため、非同期バックグラウンドタスク（`EventBroadcaster`経由の配信）との連携テストでは、`websocket_connect` のタイミングが重要。
  - `EventBroadcaster` が履歴を持たないため、接続前に発生したイベントはロストする。テストでは `Session` 作成から接続までの間に発生する初期イベントのロストを考慮する必要がある。
  - `TestClient` をコンテキストマネージャ (`with TestClient(app)`) として使用しないと Startup/Shutdown イベントが正しく処理されず、イベントループの挙動が不安定になる場合がある。
