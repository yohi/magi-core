# マルチプロバイダーLLM認証・実行 実装ガイド

本ドキュメントは、異なる認証プロトコルを持つAIサービス（Claude Code, GitHub Copilot, Antigravity）の認証フローを実装し、取得した認証情報を用いてLLMを実行するための汎用的なアーキテクチャパターンを定義します。

## 1. 共通アーキテクチャパターン

複数のLLMプロバイダーを統合する場合、以下の3層構造で実装するのが推奨されます。

1. **Auth Provider Layer**: プロトコル（OAuth 2.0/2.1, Device Flow）ごとの認証処理とトークンのライフサイクル管理。
2. **Request Transformation Layer**: 認証情報を各APIが要求する形式（Header, Proxy）に注入し、リクエストボディを正規化する層。
3. **Model Execution Layer**: 統一されたインターフェース（例: OpenAI互換API）でチャット完了リクエストを実行する層。

---

## 2. Claude Code / MCP対応サーバーの実装 (OAuth 2.1 with PKCE)

Claude Code等のMCP (Model Context Protocol) ツールは、セキュリティの高いOAuth 2.1フロー（PKCE推奨）を使用します。

### 2.1 認証フローの設計

CLIやデスクトップアプリからブラウザ認証を行う「ローカルサーバー・コールバック」方式を採用します。

1. **Code Verifier/Challenge生成**: PKCE用に暗号論的に安全なランダム文字列を生成。
2. **ローカルサーバー起動**: 一時的なポート（例: `localhost:3000`）でHTTPサーバーを起動し、`/callback` ルートを待機。
3. **ブラウザ誘導**: ユーザーを認可URLへリダイレクト。
* `response_type=code`
* `code_challenge={hash}`
* `redirect_uri=http://localhost:3000/callback`


4. **コード交換**: コールバックで `code` を受け取り、バックグラウンドで `/token` エンドポイントへPOSTしてアクセストークンを取得。

### 2.2 実装サンプル (TypeScript/Node.js)

```typescript
// 概念実証コード: OAuth 2.1 Flow
import { createServer } from 'http';
import { randomBytes, createHash } from 'crypto';

async function authenticateClaude() {
  // 1. PKCE生成
  const verifier = base64URLEncode(randomBytes(32));
  const challenge = base64URLEncode(createHash('sha256').update(verifier).digest());

  // 2. ローカルサーバーで待機
  const server = createServer(async (req, res) => {
    const url = new URL(req.url!, `http://${req.headers.host}`);
    const code = url.searchParams.get('code');
    
    if (code) {
      res.end('Authentication successful! You can close this window.');
      server.close();
      
      // 4. トークン交換
      const tokens = await exchangeCodeForToken(code, verifier);
      saveTokens(tokens); // 安全なストレージへ保存
    }
  }).listen(0); // ランダムポート

  const port = (server.address() as any).port;
  
  // 3. ブラウザを開く
  const authUrl = `https://auth.anthropic.com/authorize?response_type=code&client_id=YOUR_ID&redirect_uri=http://localhost:${port}&code_challenge=${challenge}`;
  openBrowser(authUrl);
}

```

### 2.3 LLM実行

MCPの場合、直接HTTPを叩くのではなく、MCPプロトコル（JSON-RPC via StdioまたはSSE）を通じて `sampling/createMessage` などを呼び出します。

---

## 3. GitHub Copilot / Codex の実装 (GitHub Device Flow)

CopilotはGitHubアカウントに紐付きますが、実行はOpenAI互換の特殊なプロキシサーバーを経由します。

### 3.1 認証フローの設計 (Device Flow)

CLIツールや入力デバイスが限られる環境に適した Device Flow を使用します。

1. **Device Code要求**: GitHubへ `POST /login/device/code` を送信。`user_code` と `verification_uri` を取得。
2. **ユーザーアクション**: ユーザーに `user_code` をクリップボードにコピーさせ、ブラウザを開かせる。
3. **ポーリング**: アプリ側は `POST /login/oauth/access_token` を定期的に叩き、ユーザーの承認を待つ。
4. **Copilot Token取得**: GitHubのOAuthトークン(`gho_...`)を使って、さらにCopilot専用のトークン(`tid=...`)を取得するAPIを叩く必要があります（重要）。

### 3.2 リクエスト変換 (Request Transformer)

Copilot APIはOpenAI互換ですが、厳格なヘッダー要求があります。

* **Endpoint**: `https://copilot-proxy.githubusercontent.com/v1/chat/completions`
* **Headers**:
* `Authorization`: `Bearer <copilot_internal_token>` (GitHubトークンではない)
* `Editor-Version`: `vscode/1.85.0` (VS Codeとして振る舞う必要がある場合がある)
* `Copilot-Integration-Id`: `vscode-chat`



### 3.3 実装のポイント

標準的なOpenAIクライアントライブラリを使用しつつ、`baseURL` と `headers` をオーバーライドすることで実装できます。

```typescript
import OpenAI from 'openai';

// 1. GitHub TokenからCopilot Tokenを取得 (通常30分で切れる)
const copilotToken = await getCopilotTokenFromGitHubToken(ghToken);

// 2. OpenAIクライアントの初期化
const client = new OpenAI({
  apiKey: copilotToken,
  baseURL: 'https://copilot-proxy.githubusercontent.com/v1',
  defaultHeaders: {
    'Editor-Version': 'vscode/1.85.0',
    'Editor-Plugin-Version': 'copilot-chat/0.12.0'
  }
});

// 3. 実行
const response = await client.chat.completions.create({
  model: 'gpt-4', // Copilotが許可するモデル名にマッピングが必要
  messages: [...]
});

```

---

## 4. Antigravity / 企業向けゲートウェイの実装 (Queueing & Refresh)

企業向けゲートウェイ（Antigravity等）では、アクセストークンの有効期限が短く設定されていることが多く、**並列リクエスト時のトークンリフレッシュ制御**が最大の課題になります。

### 4.1 "Thundering Herd" 対策 (Refresh Queue)

アクセストークンが切れた際、複数のリクエストが同時に `401` エラーになると、全てのリクエストが一斉にリフレッシュを試みてしまいます。これを防ぐ「Refresh Queue」パターンを実装します。

**ロジック:**

1. APIリクエストを実行。
2. `401 Unauthorized` または事前チェックで有効期限切れを検知。
3. **Mutexロック**: リフレッシュ処理が既に走っているか確認。
4. **待機**: 走っている場合、その完了を待つPromiseを返して待機キューに入れる。
5. **実行**: 走っていない場合、自分がリフレッシュAPIを叩き、新しいトークンを取得して保存。
6. **再開**: 待機していた全てのリクエストを、新しいトークンで再試行させる。

### 4.2 実装サンプル (Refresh Queue Pattern)

```typescript
class TokenManager {
  private refreshPromise: Promise<string> | null = null;

  async getToken(): Promise<string> {
    if (this.isExpired()) {
      return this.refreshToken();
    }
    return this.storage.get();
  }

  private async refreshToken(): Promise<string> {
    // 既に誰かがリフレッシュ中なら、その結果を待つ（重複実行しない）
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = (async () => {
      try {
        const newToken = await fetchNewTokenFromAPI();
        await this.storage.set(newToken);
        return newToken;
      } finally {
        this.refreshPromise = null; // リセット
      }
    })();

    return this.refreshPromise;
  }
}

```

### 4.3 モデルマッピング (Model Resolver)

企業ゲートウェイでは、ユーザーが指定するモデル名（`gpt-4`）と、実際のバックエンドのデプロイ名（`antigravity-deployment-v2`）が異なる場合があります。
リクエスト前に `Model Resolver` を通し、設定ファイルやAPIから取得したマッピング情報に基づいて `model` パラメータを差し替えるミドルウェアを挟みます。

---

## 5. まとめ：統合クライアントの作成

これら3つを統合して「認証情報を使ってLLMを使う」ための汎用クラス設計は以下のようになります。

```typescript
interface LLMProvider {
  /** 認証フローを開始し、トークンをストレージに保存する */
  authenticate(): Promise<void>;
  
  /** 保存されたトークンを使用し、OpenAI互換のリクエストを実行する */
  chat(messages: any[], options?: any): Promise<Stream>;
}

// ファクトリー関数
function getProvider(type: 'claude' | 'copilot' | 'antigravity'): LLMProvider {
  switch(type) {
    case 'claude': 
      return new McpClientProvider(...); // OAuth 2.1 + MCP
    case 'copilot': 
      return new CopilotProvider(...);   // Device Flow + Proxy Headers
    case 'antigravity': 
      return new EnterpriseProvider(...); // OAuth 2.0 + Refresh Queue
  }
}

```

### セキュリティ上の推奨事項

* **トークン保存**: ファイルシステムへの平文保存は避け、OS標準のキーストア（macOS Keychain, Windows Credential Manager）を使用するライブラリ（例: `keytar`）を利用してください。
* **プロキシ**: 企業環境での利用を想定し、環境変数 `HTTP_PROXY`, `HTTPS_PROXY` を尊重するHTTPエージェントを構成してください。
