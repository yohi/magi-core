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

## 開発ガイドライン (Development Guidelines)

### 言語ポリシー (Language Policy)
- **基本原則**: 常に**日本語**で応答してください。
- **思考プロセス**: 技術的な正確性のために英語で考えることは推奨されますが、出力は日本語で行ってください。
- **適用範囲**:
  - AIの応答、説明
  - ドキュメント (Markdown)
  - コード内のコメント、ドックストリング
  - Gitコミットメッセージ
- **例外**: 技術用語、コマンド、国際標準（プロトコル名など）、およびこのファイルのシステム定義部分。

### コンテンツ作成
- プロジェクトファイルに書き込まれるすべてのMarkdownコンテンツ（requirements.md, design.md, tasks.md, research.md, 検証レポート等）は日本語で記述する必要があります。

## Development Rules
- 3-phase approval workflow: Requirements → Design → Tasks → Implementation
- Human review required each phase; use `-y` only for intentional fast-track
- Keep steering current and verify alignment with `/prompts:kiro-spec-status`
- Follow the user's instructions precisely, and within that scope act autonomously.

---

# 技術標準とコマンド (Technical Standards & Commands)

## 環境 (Environment)
- **Python**: 3.11+
- **Package Manager**: `uv` (Required)
- **Test Framework**: `unittest`

## 主要コマンド (Key Commands)

### セットアップ & ビルド (Setup & Build)
```bash
# 依存関係の同期
uv sync

# パッケージの追加
uv add <package_name>
```

### テスト実行 (Testing)
**重要**: 変更を加えた後は必ず関連するテストを実行してください。

**全テストを実行 (Run All Tests):**
```bash
uv run python -m unittest discover -s tests -v
```

**特定のテストファイルを実行 (Run Single File):**
```bash
uv run python -m unittest tests/unit/test_cli.py
```

**特定のテストケースを実行 (Run Single Case):**
```bash
# フォーマット: path.to.module.Class.method
# 例: magiパッケージ内の tests.unit.test_cli モジュールにある TestArgumentParser クラスの test_parse_help_short メソッド
uv run python -m unittest tests.unit.test_cli.TestArgumentParser.test_parse_help_short
```

**カバレッジ計測 (Coverage):**
```bash
uv run coverage run -m unittest discover -s tests
uv run coverage report
```

## コードスタイルガイドライン (Code Style Guidelines)

### Python実装ルール
- **ドックストリング (Docstrings)**:
  - **日本語**で記述。
  - トリプルクォート `"""` を使用。
  - 形式: `要約行` -> `空行` -> `詳細説明` -> `Args/Returns/Raises`。
- **型ヒント (Type Hints)**:
  - **必須**。すべての関数引数と戻り値に型ヒントを付与。
  - `typing` (List, Dict, Optional, Any) または `str | None` 形式を使用。
- **インポート順序**:
  1. 標準ライブラリ (`import os`, `from typing import ...`)
  2. サードパーティ (`import anthropic`)
  3. ローカル (`from magi.core import ...`) - **絶対インポート推奨**

### 命名規則 (Naming Conventions)
- **ファイル/モジュール**: `snake_case` (例: `consensus_engine.py`)
- **クラス**: `CamelCase` (例: `ConsensusEngine`)
- **関数/メソッド/変数**: `snake_case` (例: `execute_voting_process`)
- **定数**: `UPPER_SNAKE_CASE` (例: `DEFAULT_TIMEOUT`)

### エラーハンドリング (Error Handling)
- カスタム例外は `magi.core.errors` 等で定義。
- ユーザー向けのエラーメッセージは**日本語**で記述することを強く推奨。
  - 開発者向けの内部エラー (`ValueError` 等) は英語でも可とするが、可能な限り日本語を含めるか、分かりやすく記述する。

### ディレクトリ構造 (Structure)
- `src/magi/`: ソースコード
  - `core/`: 合議エンジン、コンテキスト
  - `agents/`: ペルソナ定義、エージェントロジック
  - `plugins/`: プラグインシステム
- `tests/`: テストコード (ソースコードの構造をミラーリング)

## エージェントへの指示 (Instructions for Agents)
1. **実装前確認**: 既存のコードスタイル（特に日本語ドキュメントと型ヒント）を確認し、それに従うこと。
2. **テスト駆動**: 新機能追加時はテストケースを作成し、単体テスト (`Run Single Case`) で検証しながら進めること。
3. **自律性**: 必要なコンテキストは自分で収集し、タスク完了まで自律的に行動すること。不明点は質問すること。
