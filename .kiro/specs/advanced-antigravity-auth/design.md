# Advanced Antigravity Auth 基本設計書

## 1. 概要
本設計書は、Antigravity 認証システムにおける堅牢性とユーザー体験の向上を目的とした高度な機能の実装案を定義する。主な追加機能は、エンドポイント・フォールバック、自動プロジェクト・オンボーディング、および最新のクライアントメタデータ管理である。

## 2. システムアーキテクチャ

### 2.1. クラス構成
`AntigravityAuthProvider` クラスに以下のプライベートメソッドを追加し、既存の認証フローを強化する。

| メソッド名 | 役割 |
|:---|:---|
| `_fetch_with_fallback(url_suffix, ...)` | エンドポイントの順次試行とリクエスト実行 |
| `_onboard_user()` | プロジェクト未設定時の自動プロビジョニング実行 |
| `_get_headers()` | リクエストヘッダー（User-Agent, Metadata等）の生成 |

## 3. 詳細設計

### 3.1. エンドポイント・フォールバック戦略
リクエスト失敗時（接続エラーまたは5xxエラー）、以下の優先順位でエンドポイントを切り替える。

1. **Daily**: `https://daily-cloudcode-pa.sandbox.googleapis.com` (`ANTIGRAVITY_ENDPOINT_DAILY`)
2. **Autopush**: `https://autopush-cloudcode-pa.sandbox.googleapis.com` (`ANTIGRAVITY_ENDPOINT_AUTOPUSH`)
3. **Prod**: `https://cloudcode-pa.googleapis.com` (`ANTIGRAVITY_ENDPOINT_PROD`)

**アルゴリズム:**
```python
for endpoint in [DAILY, AUTOPUSH, PROD]:
    try:
        return perform_request(endpoint + url_suffix)
    except (ConnectionError, ServerError):
        continue
raise AuthenticationError("All endpoints failed")
```

### 3.2. 自動オンボーディング・メカニズム
`loadCodeAssist` が有効なプロジェクト ID を返さない場合に発動する。

- **エンドポイント**: `onboardUser`
- **リトライポリシー**:
    - 最大試行回数: 10回
    - 待機時間: 各試行間に 5秒 の固定ディレイ
- **フロー**:
    1. `onboardUser` API を呼び出し。
    2. 成功（200 OK）するまで上記ポリシーに従いリトライ。
    3. 成功後、取得した `projectId` を認証コンテキストに保存し、以降のリクエストで使用。

### 3.3. ヘッダーとメタデータ管理
`temp_auth_repo/src/constants.ts` に基づき、以下の値を定数として管理し、`_get_headers()` で生成する。

- **Constants**:
    - `ANTIGRAVITY_VERSION`: "1.15.8"
    - `X_GOOG_API_CLIENT`: "google-cloud-sdk vscode_cloudshelleditor/0.1"
- **User-Agent 形式**:
    - `Mozilla/5.0 ... Antigravity/${ANTIGRAVITY_VERSION} ...`
- **Client-Metadata (JSON)**:
    ```json
    {
      "ideType": "IDE_UNSPECIFIED",
      "platform": "PLATFORM_UNSPECIFIED",
      "pluginType": "GEMINI"
    }
    ```

## 4. データ構造の変更
`AntigravityConfig` モデルに以下のフィールドを追加（または既存のものを更新）することを検討する。
- `last_known_project_id`: オンボーディングで取得した ID をキャッシュ。
- `current_endpoint_index`: 最後に成功したエンドポイントを記憶し、次回リクエストの初期値とする（オプション）。

## 5. テスト計画
- **フォールバックテスト**: Daily エンドポイントをモックで失敗させ、Autopush に移行することを確認。
- **オンボーディングテスト**: 初回リクエストでプロジェクト ID が空の場合に `onboardUser` が規定回数リトライされることを確認。
- **ヘッダー検証**: 送信されるリクエストのヘッダーが `constants.ts` の定義と完全に一致することを確認。
