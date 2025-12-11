# Research & Design Decisions Template

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.
---

## Summary
- **Feature**: multi-api-key-support
- **Discovery Scope**: Complex Integration（複数 LLM プロバイダと外部 CLI ブリッジを跨る拡張）
- **Key Findings**:
  - 既存の LLMClient/Config は Anthropic 固定でプロバイダ選択や鍵の多重管理が未実装。
  - CLI/Plugin ガードはメタ文字検証と署名検証を備えるが、プロバイダ識別子や鍵伝搬の契約がない。
  - Guardrails/SecurityFilter/イベント記録はあるが、プロバイダ単位の監査・ヘルスチェック・失敗時挙動は未定義。

## Research Log

### プロバイダ抽象化と選択
- **Context**: 複数 API キーとプロバイダを選択的に使いたい要件（Req 1.x, 2.x）。
- **Sources Consulted**: 既存コード（config.manager, llm.client, cli.parser, consensus）、ステアリング。
- **Findings**:
  - Config ENV マッピングは `MAGI_API_KEY` のみ。モデル/エンドポイントも Anthropic 前提。
  - LLMClient は AsyncAnthropic に直接依存し、プロバイダ切替や抽象インターフェースがない。
  - CLI パーサーにプロバイダ指定オプションが存在しない。
- **Implications**: プロバイダ抽象インターフェースとレジストリ/セレクタが必要。Config と CLI の両方に provider/context を追加し、ConsensusEngine まで伝搬させる。

### 外部 CLI ブリッジ（ClaudeCode/CodexCLI/GeminiCLI/CursorCLI）
- **Context**: プラグイン/外部 CLI へ鍵とプロバイダ識別子を安全に渡す要件（Req 3.x）。
- **Sources Consulted**: plugins.loader/guard/executor, signature, CLI パターン。
- **Findings**:
  - PluginGuard がメタ文字拒否、Executor がタイムアウト処理を持つが、プロバイダ情報の契約はない。
  - プラグイン YAML にプロバイダ種別や鍵の取り扱いスキーマが存在しない。
- **Implications**: ブリッジ引数に provider を明示し、鍵の最小伝搬とエラー文脈（プロバイダ名）を追加する契約が必要。非対応プロバイダは事前に fail-fast。

### 監査・フェイルセーフと鍵保護
- **Context**: 鍵欠落/認証失敗時の挙動と監査ログ（Req 4.x）。
- **Sources Consulted**: consensus イベント記録、guardrails, security.filter。
- **Findings**:
  - イベントにはコード付与済みだがプロバイダ文脈や鍵の有無を示すフィールドはない。
  - SecurityFilter はログ/プロンプトにマーカー付与とパターン検知を行うが、鍵の扱いは前提としていない。
- **Implications**: イベント payload に provider/context を含めつつ鍵をログへ書かない規約を追加。非課金ヘルスチェックの API/CLI 可否は実装時に要確認（Research Needed）。

### プロバイダ別ヘルスチェック方針
- **Context**: Req 4.4 で非課金かつ安全なヘルスチェックが求められる。
- **Sources Consulted**: 既存コード、一般的な LLM API の無料エンドポイント。
- **Findings**:
  - Anthropic: 無料のヘルスチェックエンドポイントはなく、軽量メッセージ送信を含む全 API 呼び出しが課金対象。
  - OpenAI: `/v1/models` 参照は非課金で利用可（要 API キー）。  
  - Gemini: Google 公式で無料の HTTP ヘルスチェックエンドポイントはなく、モデルリスト取得を含む全 API 呼び出しが課金対象（モデルリストはドキュメントで参照可能な場合あり）。
- **Implications**: design.md に「ヘルスチェックは非課金エンドポイントを優先」「Anthropic/Gemini はデフォルトでスキップまたは明示オプトイン」「課金の可能性があればオプトイン」と記載し、実装タスクでも Anthropic/Gemini は課金前提でスキップ/オプトイン対応を明示する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Adapter Registry | プロバイダごとにアダプタを実装し、レジストリで選択する | 責務分離、追加プロバイダを拡張しやすい | レジストリ実装と設定スキーマ拡張が必要 | 既存 LLMClient を薄いオーケストレータに変更 |
| Branching in Client | 既存 LLMClient 内で if/else で切替 | 変更箇所が少ない | ファイル肥大化、SRP 違反で将来の追加が困難 | 推奨しない |
| External CLI only | 外部 CLI 側でプロバイダ切替を完結 | 本体改修を抑えられる | Core の合議経路と乖離し、監査/ガードが効かない | 要件を満たさない |

## Design Decisions

### Decision: プロバイダアダプタ + レジストリ方式を採用
- **Context**: 複数プロバイダ鍵と CLI/プラグイン連携を安全に切替える必要。
- **Alternatives Considered**:
  1. LLMClient 内に分岐を追加
  2. プロバイダアダプタをレジストリ経由で解決（選択）
- **Selected Approach**: アダプタ/レジストリ方式。Config/CLI で provider を受け、セレクタが適切なアダプタを返し、ConsensusEngine がそれを用いる。
- **Rationale**: SRP を保ちつつ将来の追加に耐え、テスト容易性を維持。プラグイン/CLI への provider 伝搬も共通化できる。
- **Trade-offs**: 新規ファイルとインターフェース設計が必要。初期コストは増える。
- **Follow-up**: プロバイダ別モデル名/エンドポイントと非課金ヘルスチェックの調査を実装前に行う。

## Risks & Mitigations
- プロバイダ API 差異（モデル名/パラメータ）による不整合 — レジストリに必須フィールドとバリデーションを持たせる。
- 鍵漏えいリスク — ログ/イベントで鍵をマスクし、プラグイン渡しは最小限かつメタ文字検証を維持。
- 未対応 CLI ブリッジでの誤実行 — ブリッジ契約に provider 必須を追加し、非対応時は fail-fast。

## References
- 既存コードベースとステアリングのみ参照（外部検索なし）  
