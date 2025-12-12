# Implementation Plan

- [x] 1. Config でプロバイダ別設定/鍵をロード・検証する
  - env/yaml から provider ごとの api_key/model/endpoint/options を読み込み、デフォルト値と必須フィールドを正規化する。
  - 鍵をログ/イベントに出さないマスキング方針を適用し、部分的欠落時は明示エラーを返す。
  - リロード（reload）でプロバイダ構成を再読込できるようにし、デフォルト解決順（flag > config > env > built-in）に合わせる。
  - _Requirements: 1.1, 1.3, 1.5, 2.4, 2.5, 4.5_

- [x] 2. ProviderRegistry/Selector を実装し、プロバイダ選択と検証を行う
  - サポートする ProviderId を登録し、未登録や必須パラメータ不足時に fail-fast するレジストリを用意する。
  - ProviderSelector で CLI/config から選択された provider を検証し、デフォルト選択を出力に明示する。
  - Guardrails/SecurityFilter 実行前に provider 存在と鍵有無をチェックし、コンテキストを ConsensusEngine/Bridge に伝搬する。
  - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3, 2.5, 4.3, 4.5_

- [ ] 3. プロバイダアダプタ群を用意し、共通インターフェースで LLM 呼び出しを行う
  - 共通 ProviderAdapter インターフェースで send/health/error 正規化を定義し、認証失敗は再試行しないポリシーにまとめる。
  - AnthropicAdapter を実装し、課金前提のためヘルスチェックはデフォルトスキップ/オプトインにする。
  - OpenAIAdapter を実装し、`/v1/models` の非課金ヘルスチェックとモデル/パラメータ検証を行う。
  - GeminiAdapter を実装し、課金前提でヘルスチェックはデフォルトスキップ/オプトインにし、モデル/エンドポイント必須を検証する。
  - _Requirements: 1.2, 2.3, 2.4, 4.2, 4.4_

- [ ] 4. CLI/Bridge で provider コンテキストを扱い、安全に外部 CLI を起動する
  - CLI パーサーに `--provider` を追加し、選択結果を出力に明示する。未知/未設定時は actionable エラーを返す。
  - BridgeAdapter で provider ID と必要な鍵のみを env/stdin で渡し、PluginGuard 再検証後に外部 CLI を実行する。
  - 未対応プロバイダのブリッジ呼び出しは事前に拒否し、認証エラーは provider 文脈付きで返す。
  - _Requirements: 2.1, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 5. 監査イベントとロギングを拡張し、鍵を守りつつプロバイダ情報を記録する
  - consensus イベントに provider/missing_fields/auth_error を任意フィールドとして追加し、後方互換を維持する。
  - ログ/イベントで鍵をマスクし、Guardrails/SecurityFilter イベントと統合しやすい形式にそろえる。
  - _Requirements: 1.4, 4.1, 4.5_

- [ ] 6. テスト: Registry/Selector/Adapters/CLI/Bridge の動作を検証する
  - Unit: ConfigLoader/Registry/Selector のデフォルト解決、未登録/欠落エラー、Adapter のエラー正規化。
  - Integration: ConsensusEngine 経由で provider ルーティングと fail-fast を確認。BridgeAdapter が未対応 provider を拒否し、PluginGuard を通過することを検証。
  - E2E (CLI): `magi ask --provider openai` で選択表示と正常系、未設定/未知 provider のエラーメッセージを確認。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5_
