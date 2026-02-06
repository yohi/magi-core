
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

## 審議中スタンプの追加 (2026-02-05)
- `webui_mock/dashboard.html` において、`THINKING` フェーズ中に「審議中」スタンプを表示するように変更。
- `void element.offsetWidth;` を使用してリフローを強制することで、`display: none` から `display: flex` に切り替えた直後の CSS アニメーションを確実に実行させている。
- スタンプの色は `--magi-orange` を使用。

## 2026-02-05 Task: Faster/Chaotic Blink Animation
- **Animation Logic**:
  - Replaced `setInterval` (100ms) with recursive `setTimeout` (random 20-80ms) for the `.active` class toggle on monoliths.
  - This creates a more "jittery" and chaotic effect suitable for the "MAGI" system aesthetic.
- **Resource Management**:
  - Used recursive `setTimeout` pattern which is safer than `setInterval` for potentially overlapping or heavy operations (though purely visual here).
  - Ensured `clearTimeout` is called on all state transitions (Reset, Resolve, Start) to prevent zombie timers.
## Chaos Blinking Verification
- Verified randomized intervals in THINKING phase.
- Intervals observed consistently between 20ms and 80.5ms (after filtering overhead).
- Measurement methodology: MutationObserver on .monolith class changes.

## Modal Implementation for Unit Configuration (2026-02-05)
- Added a `position: fixed` modal overlay to `dashboard.html` for unit configuration.
- Used `unitSettings` object to store per-unit state (model, temp, persona).
- Default personas set for Melchior (Scientist), Balthasar (Mother), Casper (Woman).
- Modal matches EVA aesthetic (black/orange, monospaced).
- Unit Settings Modal functionality verified in dashboard.html.
- State persistence for unitSettings object works as expected (verified via Melchior temperature change).
- Cancel action correctly discards changes (verified via Casper model change).
- Default personas for all units match the specifications (Scientist, Mother, Woman).

- **Animation Logic**: Switched MAGI thinking animation from color-shift to opacity-flicker (0.1 <-> 1.0) to simulate "processing" vs "active" states more visually. Used CSS specificity with `.magi-container.thinking` to isolate the effect to the thinking phase only.

## Opacity Blink Verification (2026-02-05)
- **Visual Pattern**: Verified that the thinking animation now uses opacity flicker (0.1 <-> 1.0) instead of color shifting.
- **States Verified**:
    - **Idle**: All `.monolith` elements have `opacity: 1` (default visible).
    - **Thinking**: `.magi-container` correctly gains the `.thinking` class, which triggers `opacity: 0.1` on all monoliths.
    - **Blinking**: The `.active` class correctly restores `opacity: 1` on the targeted monolith, creating the "bright blink" effect.
- **Color Consistency**: Confirmed that the active monolith retains its blue fill (`#4a7fb0`) and does NOT change to orange, matching the requirement to move away from color-based blinking.
- **Verification Method**: Used headless browser (Playwright/Chrome DevTools) to measure computed styles and verify class state transitions.
- **Layout Verification (2026-02-05)**:
    - Verified `webui_mock/dashboard.html` layout positioning using Playwright.
    - Result Console (`.result-console`): left=20px, bottom=20px, visible in RESOLVED state.
    - Log Panel (`.log-panel`): right=20px, bottom=190px, top=80px.
    - Control Panel (`.control-panel`): right=20px, bottom=20px.
    - Verified no overlap between `.log-panel` and `.control-panel`.
    - Note: Used `chrome-devtools_navigate_page` to access `file://` URLs.

## Monolith Visual Refinement (2026-02-05)
- **SVG Transition Isolation**:
  - Issue: Applying opacity to the parent `.monolith` container faded the entire element, including the orange border which was required to remain visible.
  - Fix: Kept `.monolith` at `opacity: 1` and applied opacity transitions specifically to the inner `.fill-poly` SVG element.
  - Requires: Correct CSS selection (`.thinking .monolith .fill-poly` vs `.thinking .monolith.active .fill-poly`) to target the child element based on the parent's state class.
- **Default State Modification**:
  - Changed the default inline `fill` attribute of SVG polygons from Blue (`#4a7fb0`) to Green (`#3cae88`) to match the new "Idle" state requirement, ensuring visual consistency without relying on JS initialization.

## OpenAI Codex Authentication Discovery
- **Repository Analyzed**: `numman-ali/opencode-openai-codex-auth`
- **Auth Flow**: Authorization Code Flow with PKCE (S256).
- **Client ID**: `app_EMoamEEZ73f0CkXaXp7hrann`
- **Endpoints**:
  - Auth: `https://auth.openai.com/oauth/authorize`
  - Token: `https://auth.openai.com/oauth/token`
  - API Base: `https://chatgpt.com/backend-api`
- **Critical Headers**:
  - `chatgpt-account-id`: Must be extracted from the JWT access token.
  - `originator`: `codex_cli_rs`
  - `OpenAI-Beta`: `responses=experimental`
- **Differences from Copilot**:
  - Uses OpenAI Auth (auth.openai.com) instead of GitHub Auth.
  - Uses PKCE instead of Device Flow.
  - Uses `chatgpt.com` endpoints instead of `api.githubcopilot.com`.

## 2026-02-05 Task: OpenAI Codex Auth Provider
- PKCE (S256) の認可コードフローを実装し、アクセストークン/リフレッシュトークン/IDトークンのクレームを保存する。
- `chatgpt_account_id` は `AuthContext.extras` に格納し、利用側で参照できるようにした。
- 既定のリダイレクトは `http://localhost:1455/auth/callback`、ポート衝突時はランダムポートにフォールバック。
