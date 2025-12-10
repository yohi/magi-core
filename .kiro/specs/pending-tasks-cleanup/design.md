# Technical Design Document

## Overview
本機能は、`magi` CLI における未実装・不整合を解消し、合議結果提示、レビュー統合、サニタイズ監査、投票検証フェイルセーフ、トークン圧縮精度、メタデータ整合、テスト健全性を回復させる。利用者は `magi ask` で安定した合議結果を取得し、`magi spec` で 3 賢者レビューを確認できる。セキュリティ担当は禁止パターン除去の監査ログを確認でき、運用者はトークン圧縮と投票検証のフェイルセーフ履歴を追跡できる。

### Goals
- `magi ask` を合議エンジンに統合し、フェイルセーフを含む結果表示を実現する。
- `magi spec` に 3 賢者レビュー出力と進行ステータス表示を統合する。
- サニタイズ・投票検証・トークン圧縮で監査可能なログを残し、メタデータとテストの整合を回復する。

### Non-Goals
- 新規 UI/GUI の追加は行わない。
- 新しい LLM モデル選定や推論パイプラインの刷新は範囲外。
- プロダクション運用の監視基盤構築は対象外（ログは既存チャネルへ出力）。

## Architecture

### Existing Architecture Analysis
- CLI → ConsensusEngine（Thinking/Debate/Voting）→ Output/Plugins のレイヤード構造を維持する。
- TokenBudgetManager、TemplateLoader、SchemaValidator、QuorumManager、SecurityFilter/PluginGuard がハードニングを担う。
- unittest ベースのテスト構成（unit/property/integration）を踏襲し、プラグインローダー property テストを再有効化する。

### High-Level Architecture
```mermaid
graph TB
  CLI[CLI Commands]
  Ask[Ask Command]
  Spec[Spec Command]
  CE[ConsensusEngine]
  TL[TemplateLoader]
  TB[TokenBudgetManager]
  SV[SchemaValidator Voting]
  SF[SecurityFilter]
  PL[PluginLoader cc-sdd]
  LOG[Audit Logging]
  META[Spec Metadata Sync]

  CLI --> Ask --> CE
  CLI --> Spec --> PL --> CE
  CE --> TB
  CE --> SV
  CE --> SF
  TB --> LOG
  SF --> LOG
  SV --> LOG
  PL --> LOG
  META --> LOG
```

### Architecture Integration
- 既存パターン保持: CLI エントリーポイントと ConsensusEngine の責務分離を維持。
- 新規要素: Voting 用 jsonschema 検証とリトライ、サニタイズ監査ログ、要約付き圧縮ログ、メタ同期処理を追加。
- 技術整合: Python 3.11、既存 logging 設定を継続利用。jsonschema 依存は既存利用有無を確認のうえ再利用/追加。
- Steering 準拠: Core/Plugin 分離とハードニング指針（token budget, schema validation, logging）に合致。

### Technology Alignment
- 新規外部依存は原則追加しない。jsonschema が未導入なら標準的な `jsonschema` パッケージを追加検討。
- ロギングは既存 logger と監査用出力先（ファイル/STDERR）を再利用。
- CLI フローは argparse ベースの既存構造に統合し、新規コマンド追加は行わない。

### Key Design Decisions
- **Decision**: Voting ペイロードを jsonschema 検証し、最大 N 回リトライ後にフェイルセーフを返す。
  - **Alternatives**: 手書き検証のみ / 例外即フェイル / リトライなし。
  - **Rationale**: 構造保証と再生成で安定性を確保しつつ、過剰リトライを防ぐ。
  - **Trade-offs**: スキーマ管理とリトライコストが増えるが、整合性と監査性を向上。
- **Decision**: TokenBudgetManager に要約ステップを追加し、削減ログにサイズ前後・保持率・要約有無を記録。
  - **Alternatives**: 重要度選択のみ / 全面要約のみ。
  - **Rationale**: 精度と監査性の両立。重要度抽出後に要約で情報損失を抑制。
  - **Trade-offs**: 追加計算コストとログ肥大の可能性。閾値で制御。
- **Decision**: SecurityFilter で禁止パターン除去時に `removed_patterns` と監査ログへマスク済み断片を記録。
  - **Alternatives**: 件数のみ記録 / ログなし。
  - **Rationale**: 追跡性と再発防止の根拠確保。
  - **Trade-offs**: ログ量増加とマスク実装コスト。過剰情報を避けるため断片マスクを徹底。

## System Flows

### `magi ask` 合議実行フロー
```mermaid
sequenceDiagram
  participant U as User
  participant CLI as CLI
  participant CE as ConsensusEngine
  participant TB as TokenBudgetManager
  participant SV as SchemaValidator
  participant LOG as AuditLog

  U->>CLI: magi ask "<question>"
  CLI->>CE: 合議リクエスト
  CE->>TB: コンテキスト圧縮(要約含む)
  CE->>SV: Voting ペイロード検証+リトライ
  CE-->>CLI: 合議結果 or フェイルセーフ
  TB-->>LOG: 削減ログ出力
  SV-->>LOG: 検証結果ログ
```

### `magi spec` レビュー統合フロー
```mermaid
sequenceDiagram
  participant U as User
  participant CLI as CLI
  participant PL as PluginLoader cc-sdd
  participant CE as ConsensusEngine
  participant LOG as AuditLog

  U->>CLI: magi spec --review
  CLI->>PL: レビュー実行
  PL->>CE: 必要時合議呼び出し
  PL-->>CLI: 賢者別レビュー出力
  CLI-->>LOG: ステータス/結果ログ
```

### トークン圧縮と監査ログ
```mermaid
flowchart TB
  S[入力コンテキスト取得] --> C{閾値超過?}
  C -- No --> K[圧縮せず通過]
  C -- Yes --> P[重要度選択]
  P --> Y[要約ステップ]
  Y --> R[再計算後出力]
  R --> L[削減ログ記録]
```

### SecurityFilter 監査
```mermaid
flowchart TB
  I[入力テキスト] --> D[禁止パターン検知]
  D -->|一致| X[除去とマスク]
  X --> RP[removed_patterns 記録]
  X --> AL[監査ログ出力]
  D -->|非一致| P[通過]
```

## Requirements Traceability
| Requirement | 概要 | 主担当コンポーネント | 補助コンポーネント | フロー |
|-------------|------|----------------------|--------------------|--------|
| R1 | magi ask 合議実行と結果提示 | CLI Ask, ConsensusEngine | TokenBudgetManager, SchemaValidator, Logging | 合議実行フロー |
| R2 | magi spec レビュー統合表示 | CLI Spec, PluginLoader cc-sdd | ConsensusEngine, Logging | レビュー統合フロー |
| R3 | 禁止パターン監査ログ | SecurityFilter | Logging | SecurityFilter 監査 |
| R4 | Voting スキーマ検証+リトライ | SchemaValidator | ConsensusEngine, Logging | 合議実行フロー |
| R5 | 要約付きトークン圧縮と精緻ログ | TokenBudgetManager | Logging | 圧縮フロー |
| R6 | メタ整合・property テスト復活 | Spec Metadata Sync, PluginLoader Tests | Logging, CI | 変更なし（運用手順） |

## Components and Interfaces

### CLI Layer
#### AskCommand
- **Responsibility**: ユーザ入力を受け、ConsensusEngine を起動し結果を表示。
- **Dependencies**: ConsensusEngine, Logging, TokenBudgetManager（間接）。
- **Service Interface (Python 型イメージ)**:
```python
def run_ask(question: str, ctx: AskContext) -> AskResult:
    ...
```
- **Preconditions**: 質問文字列が空でないこと。
- **Postconditions**: 合議結果またはフェイルセーフを表示し、監査ログを残す。

#### SpecCommand
- **Responsibility**: cc-sdd プラグインを呼び出し、賢者レビューとステータスを表示。
- **Dependencies**: PluginLoader, ConsensusEngine（必要時）, Logging.
```python
def run_spec_review(target: str, ctx: SpecContext) -> SpecReviewResult:
    ...
```
- **Preconditions**: 対象仕様のパス/名前が有効。
- **Postconditions**: 賢者別レビューと進行ステータスを出力しログに記録。

### ConsensusEngine
- **Responsibility**: Thinking/Debate/Voting を統括し、トークン圧縮と検証を組み合わせる。
- **Inbound**: CLI Commands, PluginLoader.
- **Outbound**: TokenBudgetManager, SchemaValidator, Logging.
- **Integration Strategy**: 既存フローを拡張し、圧縮後に要約、Voting 前にスキーマ検証とリトライを挿入。

### TokenBudgetManager
- **Responsibility**: 重要度選択＋要約でトークン削減し、削減ログを生成。
- **Outbound**: Logging.
- **Contract**:
```python
def reduce_with_summary(chunks: list[ContextChunk], budget: TokenBudget) -> ReductionResult:
    ...
```
- **Postconditions**: 削減前後サイズ、保持率、要約有無を含む ReductionLogEntry を返す。

### SchemaValidator (Voting)
- **Responsibility**: Voting ペイロードを jsonschema で検証し、リトライを制御。
- **Outbound**: Logging.
- **Contract**:
```python
def validate_voting_payload(payload: dict, schema: dict, retry: int) -> ValidationOutcome:
    ...
```
- **Postconditions**: 成功時は正当化済みペイロード、失敗時はフェイルセーフフラグと理由。

### SecurityFilter
- **Responsibility**: 禁止パターン検知・除去、`removed_patterns` 記録、監査ログ出力。
- **Inbound**: ConsensusEngine 入出力、PluginGuard。
- **Outbound**: Logging.
- **Contract**:
```python
def sanitize(text: str) -> SanitizedResult:
    ...
```
- **Postconditions**: マスク済み除去断片とパターン ID を監査ログへ出力。

### PluginLoader / cc-sdd Integration
- **Responsibility**: 3 賢者レビューの実行と集約表示。property テストを有効化し CI で検証。
- **Integration**: 既存 plugin 実行パスを維持し、戻り値フォーマットを CLI で整形表示。

### Spec Metadata Sync
- **Responsibility**: `.kiro/specs/magi-core/spec.json` の remaining_tasks を tasks.md と同期。
- **Contract**:
```python
def sync_spec_metadata(tasks: TasksStatus) -> SpecMetaUpdate:
    ...
```
- **Postconditions**: メタデータ整合、監査ログへの記録。

### Logging/Audit
- **Responsibility**: 合議、サニタイズ、検証、圧縮、メタ同期の監査ログを統一フォーマットで出力。
- **Format**: timestamp, stage, result, details(masked), counts, size_before/after, retry_count, failure_reason.

## Data Models
- **VotingPayload (概要)**: `{ "voter": str, "proposal": str, "justification": str, "score": float, "confidence": float }`
- **ValidationOutcome**: `{ "ok": bool, "errors": list[str], "retries": int, "fail_safe": bool }`
- **ReductionLogEntry**: `{ "size_before": int, "size_after": int, "retain_ratio": float, "summary_applied": bool, "strategy": str }`
- **SanitizationLogEntry**: `{ "pattern_id": str, "count": int, "masked_snippet": str }`
- **SpecMetaUpdate**: `{ "remaining_tasks": int, "synced_at": str, "source": str }`

## Error Handling
- **User Errors (CLI)**: 無効引数・対象なし → 400 系相当でメッセージ表示。
- **Business Errors**: スキーマ検証失敗、クオーラム未達 → フェイルセーフ応答と理由表示、ログ記録。
- **System Errors**: LLM/API 障害、IO 障害 → リトライ後にフェイルセーフ、スタックはログのみ。
- **Logging**: 失敗段階・理由・リトライ回数を監査ログに残し、CLI は簡潔な要約のみ表示。

## Testing Strategy
- **Unit**:
  - TokenBudgetManager: 要約あり/なしの削減率計算。
  - SecurityFilter: 禁止パターン検知と `removed_patterns` 記録。
  - SchemaValidator: スキーマ成功/失敗/リトライ上限の分岐。
  - CLI Ask: 成功・フェイルセーフの出力整形。
- **Integration**:
  - `magi ask` フローで合議→圧縮→検証→結果表示。
  - `magi spec --review` で cc-sdd プラグイン出力集約。
  - Logging 出力フォーマットとマスク確認。
- **Property**:
  - PluginLoader property テストを有効化し、プラグイン登録・実行が総称的入力で失敗しないこと。
- **E2E (optional)**:
  - 環境変数設定下での CLI 実行パス確認。

## Security Considerations
- サニタイズ: 禁止パターン除去時にマスクを徹底し、生データ漏洩を防止。
- ログ: 機微情報を含む場合は省略/マスクし、出力先を設定可能にする。
- フェイルセーフ: 検証失敗時は安全側応答を返し、再試行回数を制限。

## Performance & Scalability
- トークン圧縮の要約は閾値超過時のみ実施し、コストを抑制。
- リトライ回数とコンテキスト要約有無を設定化し、負荷と品質を調整。
- ログ量増加に備え、ログレベル/キーでフィルタ可能とする。

## Migration Strategy
```mermaid
flowchart TB
  M1[Phase1 設計/実装] --> M2[Phase2 テスト有効化]
  M2 --> M3[Phase3 メタ同期適用]
  M3 --> M4[Phase4 本番反映]
  M4 --> M5[Phase5 監査ログ確認]
  M5 --> M6[Rollback 条件: テスト失敗 or 過剰ログ]
```
- Phase1: 機能追加とローカル検証。
- Phase2: 無効化されていた property テストを有効化し CI で実行。
- Phase3: spec メタデータを tasks 状態と同期。
- Phase4: 本番反映（リリース手順に従う）。
- Phase5: 監査ログとフェイルセーフの挙動を確認。
- Rollback: テスト失敗やログ肥大が確認された場合、前バージョンへロールバックし設定を見直す。
