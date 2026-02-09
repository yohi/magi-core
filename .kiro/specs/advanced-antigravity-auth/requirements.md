# Advanced Antigravity Auth 要件定義書

## 1. 背景
現在の Antigravity 認証実装は基本的な OAuth フローをサポートしているが、信頼性とユーザー体験の向上（特に Google Cloud プロジェクトが事前設定されていないユーザー向け）のために、`opencode-antigravity-auth` リファレンス実装から高度な機能を移植する必要がある。

## 2. 目的
- 認証プロセスの堅牢性を高めるためのエンドポイント・フォールバック機構を導入する。
- マネージドプロジェクトが存在しない場合、自動的にオンボーディング（プロビジョニング）を行う機能を追加する。
- Antigravity API との互換性を維持し、"Version no longer supported" エラーを回避するためにヘッダーとクライアントメタデータを最新化する。

## 3. 機能要件

### 3.1. エンドポイント・フォールバック (Req 1)
- Antigravity API リクエストにおいて、以下の順序でエンドポイントを試行するフォールバック機構を実装すること。
    1. Daily (https://daily-cloudcode-pa.sandbox.googleapis.com)
    2. Autopush (https://autopush-cloudcode-pa.sandbox.googleapis.com)
    3. Prod (https://cloudcode-pa.googleapis.com)
- 接続エラーや 5xx エラーが発生した場合、次のエンドポイントへ自動的に切り替えること。

### 3.2. 自動プロジェクト・オンボーディング (Req 2)
- `loadCodeAssist` 呼び出しが失敗するか、有効なプロジェクト ID を返さなかった場合、自動的にオンボーディングプロセスを開始すること。
- `onboardUser` エンドポイントを使用して、ユーザーに代わってマネージドプロジェクトをプロビジョニングすること。
- オンボーディングが成功するまで、一定回数（最大10回程度）の再試行とディレイ（5秒程度）を行うこと。
- プロビジョニングされたプロジェクト ID を永続化し、以降の API リクエストで使用すること。

### 3.3. ヘッダーとクライアントメタデータの更新 (Req 3)
- Antigravity API へのリクエストヘッダーに以下の項目を含めること。
    - `User-Agent`: `Antigravity/1.15.8` を含む最新の形式。
    - `X-Goog-Api-Client`: `google-cloud-sdk vscode_cloudshelleditor/0.1` 等の識別子。
    - `Client-Metadata`: `ideType`, `platform`, `pluginType` を含む JSON 文字列。
- `User-Agent` 等のバージョン情報は、将来的な更新を容易にするために定数として管理すること。

## 4. 受入条件
- [ ] エンドポイントのリストが定義され、接続失敗時にフォールバックが行われることがテストで確認されていること。
- [ ] プロジェクト未設定の状態で認証を開始した際、`onboardUser` が呼び出され、最終的に有効なプロジェクト ID が取得できること。
- [ ] リクエストヘッダーに `Client-Metadata` が正しく設定されていること。
- [ ] 全てのコードコメントとドキュメントが日本語で記述されていること。

## 5. 制約事項
- 既存の OAuth 認可コードフローとの互換性を維持すること。
- 外部リポジトリ `temp_auth_repo` の実装ロジック（`src/plugin/project.ts` および `src/constants.ts`）を参考にすること。
