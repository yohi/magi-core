# AI-DLC and Spec-Driven Development

Kiro-style Spec Driven Development implementation on AI-DLC (AI Development Life Cycle)

## Project Memory
Project memory keeps persistent guidance (steering, specs notes, component docs) so Codex honors your standards each run. Treat it as the long-lived source of truth for patterns, conventions, and decisions.

- Use `.kiro/steering/` for project-wide policies: architecture principles, naming schemes, security constraints, tech stack decisions, api standards, etc.
- Use local `AGENTS.md` files for feature or library context (e.g. `src/lib/payments/AGENTS.md`): describe domain assumptions, API contracts, or testing conventions specific to that folder. Codex auto-loads these when working in the matching path.
- Specs notes stay with each spec (under `.kiro/specs/`) to guide specification-level workflows.

## Project Context

### Paths
- Steering: `.kiro/steering/`
- Specs: `.kiro/specs/`

### Steering vs Specification

**Steering** (`.kiro/steering/`) - Guide AI with project-wide rules and context
**Specs** (`.kiro/specs/`) - Formalize development process for individual features

### Active Specifications
- Check `.kiro/specs/` for active specifications
- Use `/prompts:kiro-spec-status [feature-name]` to check progress

## 開発ガイドライン
- **言語ポリシー**: 常に日本語で応答してください。技術的な正確性のために英語で考えることは構いませんが、すべての出力（応答、ドキュメント、コメント、コミットメッセージ）は、明示的に要求されない限り日本語で記述する必要があります。
  - **適用範囲**: このポリシーはAIの応答、新規作成するドキュメント、コード内のコメント、コミットメッセージに適用されます。
  - **例外**: このドキュメント（AGENTS.md）内の一部セクション（プロジェクト構造定義、ワークフローコマンド、技術用語など）は、国際的な互換性やツールチェーンとの統合のため英語で記述されている場合があります。
- プロジェクトファイルに書き込まれるすべてのMarkdownコンテンツ（例: requirements.md、design.md、tasks.md、research.md、検証レポート）は日本語で記述する必要があります。
- コードコメントは可読性向上のため日本語で記述することを推奨します。
- Gitコミットメッセージは日本語で記述することを推奨します。

## Minimal Workflow
- Phase 0 (optional): `/prompts:kiro-steering`, `/prompts:kiro-steering-custom`
- Phase 1 (Specification):
  - `/prompts:kiro-spec-init "description"`
  - `/prompts:kiro-spec-requirements {feature}`
  - `/prompts:kiro-validate-gap {feature}` (optional: for existing codebase)
  - `/prompts:kiro-spec-design {feature} [-y]`
  - `/prompts:kiro-validate-design {feature}` (optional: design review)
  - `/prompts:kiro-spec-tasks {feature} [-y]`
- Phase 2 (Implementation): `/prompts:kiro-spec-impl {feature} [tasks]`
  - `/prompts:kiro-validate-impl {feature}` (optional: after implementation)
- Progress check: `/prompts:kiro-spec-status {feature}` (use anytime)

## Development Rules
- 3-phase approval workflow: Requirements → Design → Tasks → Implementation
- Human review required each phase; use `-y` only for intentional fast-track
- Keep steering current and verify alignment with `/prompts:kiro-spec-status`
- Follow the user's instructions precisely, and within that scope act autonomously: gather the necessary context and complete the requested work end-to-end in this run, asking questions only when essential information is missing or the instructions are critically ambiguous.

## Steering Configuration
- Load entire `.kiro/steering/` as project memory
- Default files: `product.md`, `tech.md`, `structure.md`
- Custom files are supported (managed via `/prompts:kiro-steering-custom`)

---

# 技術標準とコマンド

## 環境
- **Python**: 3.11+
- **パッケージマネージャ**: `uv`（依存関係管理に必須）

## 主要コマンド

### セットアップ
```bash
uv sync
```

### テスト
このプロジェクトは主要なフレームワークとして `unittest` を使用しています。

**全テストを実行:**
```bash
uv run python -m unittest discover -s tests -v
```

**特定のテストファイルを実行:**
```bash
uv run python -m unittest tests/unit/test_cli.py
```

**特定のテストケースを実行:**
```bash
# フォーマット: path.to.module.Class.method
uv run python -m unittest magi.tests.unit.test_cli.TestArgumentParser.test_parse_help_short
```

**カバレッジ:**
```bash
uv run coverage run -m unittest discover -s tests
uv run coverage report
```

## コードスタイルガイドライン

### 言語とドキュメント
- **ドックストリング**: **日本語**で記述する必要があります。
  - ドックストリングにはトリプルクォート `"""` を使用してください。
  - 構造: 簡潔な要約行、空行、詳細な説明。
- **コメント**: **日本語**で記述する必要があります。
- **コミットメッセージ**: **日本語**で記述する必要があります。

### 型ヒント
- **厳密な型付け**: すべての関数引数と戻り値に型ヒントを使用してください。
- `typing` モジュール（`List`、`Dict`、`Any`、`Optional`）またはサポートされている場合はモダンなユニオン構文（`str | None`）を使用してください。

### 命名規則
- **ファイル/モジュール**: `snake_case`（例: `consensus_engine.py`）
- **クラス**: `CamelCase`（例: `ConsensusEngine`）
- **関数/メソッド**: `snake_case`（例: `execute_voting_process`）
- **変数**: `snake_case`
- **定数**: `UPPER_SNAKE_CASE`

### アーキテクチャとパターン
- **インポート**:
  1. 標準ライブラリ
  2. サードパーティライブラリ
  3. ローカルアプリケーションのインポート（絶対インポートを推奨、例: `from magi.core import ...`）
- **エラーハンドリング**:
  - 該当する場合は `magi.core.errors` で定義された特定の例外を使用してください。
  - 明確なエラーメッセージ（日本語）で適切に失敗させてください。

### テスト標準
- テストはソース構造をミラーリングした `tests/` ディレクトリに配置してください。
- `unittest.TestCase` を使用してください。
- 外部依存関係（LLM呼び出し、ファイルI/O）はモックしてください。
