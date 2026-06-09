# /magi スラッシュコマンド設計仕様

**作成日**: 2026-06-09  
**ステータス**: 承認済み  
**スコープ**: magi本体の `--preset` オプション追加 + Claude Code / OpenCode 向けスラッシュコマンド定義

---

## 概要

AIエージェント環境（Claude Code / OpenCode）から `/magi <質問>` または `/magi:arch <質問>` のようなスラッシュコマンドで MAGI System の合議判定を呼び出せるようにする。

ペルソナセット（3賢者の人格定義）は `magi.yaml` の `presets` セクションで一元管理し、二重管理を排除する。

---

## ゴール

- `Claude Code` と `OpenCode` の両方でスラッシュコマンドとして動作する
- `/magi` でデフォルトプリセット（赤木ナオコの3側面）、`/magi:arch` でアーキテクチャレビュープリセットが使える
- 出力は構造化テキスト（Thinking / Debate / Voting フェーズ別）
- プリセットの追加はスキルファイル1つ + `magi.yaml` 1エントリで完結する

---

## アーキテクチャ

```
ユーザー: /magi:arch コンテキストを全部メモリに持つべき？
    ↓
.claude/skills/magi-arch/SKILL.md が発火（description マッチ）
    ↓
uv run magi ask --preset arch "コンテキストを全部メモリに持つべき？"
    ↓
magi本体: magi.yaml の presets.arch を読み PersonaManager.apply_overrides()
    ↓
Thinking → Debate → Voting（並列 asyncio）
    ↓
構造化テキスト出力 → チャット画面に表示
```

---

## Section 1: magi 本体の拡張

### 1-1. `magi.yaml` のプリセット構造

```yaml
presets:
  default:
    melchior: "あなたはMAGIシステムのMELCHIOR-1です。科学者としての赤木ナオコの人格として振る舞い..."
    balthasar: "あなたはMAGIシステムのBALTHASAR-2です。母親としての赤木ナオコの人格として振る舞い..."
    casper: "あなたはMAGIシステムのCASPER-3です。女としての赤木ナオコの人格として振る舞い..."
  arch:
    melchior: "あなたはシステムアーキテクトです。大局的な設計判断と長期的な技術的影響を重視して..."
    balthasar: "あなたはリードエンジニアです。実装の現実性、品質、チームへの影響を重視して..."
    casper: "あなたはクリエイターです。革新性、ユーザー体験、新しい可能性を重視して..."
```

**後方互換**: `presets` セクションがない `magi.yaml` は従来通り動作する。`--preset default` 省略時は既存の `base_prompt` をそのまま使う。

### 1-2. CLI の変更

```bash
magi ask "スイカは果物？"                    # --preset 省略 = default
magi ask --preset default "スイカは果物？"  # 明示指定
magi ask --preset arch "スイカは果物？"     # archプリセット
```

### 1-3. 変更ファイル

| ファイル | 変更内容 |
|---|---|
| `src/magi/config/settings.py` | `presets: Dict[str, Dict[str, str]] = Field(default_factory=dict)` フィールド追加 |
| `src/magi/cli/parser.py` | `--preset <name>` オプション追加 |
| `src/magi/cli/main.py` | preset 読み込み → `PersonaManager.apply_overrides()` に渡す処理追加 |
| `src/magi/agents/persona.py` | 変更不要（既存の `apply_overrides()` をそのまま活用） |

---

## Section 2: スラッシュコマンド定義

### 2-1. ファイル配置

```
magi-core/
└── .claude/
    └── skills/
        ├── magi/
        │   └── SKILL.md          # /magi <質問>（defaultプリセット）
        └── magi-arch/
            └── SKILL.md          # /magi:arch <質問>
```

OpenCode は `.claude/skills/` を探索するため、同一ファイルが両エージェントで機能する。  
新プリセット追加 = `magi.yaml` に1エントリ + `.claude/skills/magi-<name>/SKILL.md` を1ファイル追加するだけ。

### 2-2. SKILL.md 構造（デフォルト）

```yaml
---
name: magi
description: MAGIシステムの3賢者（科学者・母親・女としての赤木ナオコ）に質問して合議判定を得る。質問への多角的な判断が必要なとき、あるいはユーザーが /magi と入力したときに使う。
---

# MAGI System — デフォルトプリセット

## 実行手順

1. `$ARGUMENTS` をユーザーの質問として受け取る
2. プロジェクトルートで以下を実行:
   ```bash
   uv run magi ask "$ARGUMENTS"
   ```
3. 出力をそのままチャットに返す

## 注意事項

- 質問は必ず指定すること（空の場合はユーザーに質問を求める）
- `uv` が PATH にない場合は `python -m magi ask "$ARGUMENTS"` を試みる
- 実行にはプロジェクトルートの `magi.yaml` または環境変数 `MAGI_ANTHROPIC_API_KEY` が必要
```

### 2-3. SKILL.md 構造（arch プリセット）

デフォルトと同一構造で、実行コマンドのみ異なる:

```bash
uv run magi ask --preset arch "$ARGUMENTS"
```

---

## Section 3: エラーハンドリング

| ケース | 挙動 |
|---|---|
| 存在しないプリセット名 | `Unknown preset: 'xxx'. Available: <magi.yamlのpresets keys一覧>` を動的生成して表示し終了コード1 |
| `presets` セクションなし | 既存の `base_prompt` をそのまま使用（後方互換） |
| `$ARGUMENTS` が空 | スキルの `description` に明記 + CLI側の既存バリデーション（`"Usage: magi ask <question>"`）が発動 |
| `uv` が PATH にない | スキルに `python -m magi` フォールバック手順を記載 |
| プリセットのペルソナ定義が一部欠けている | 欠けているペルソナは `base_prompt` をそのまま使用（部分上書き） |

---

## テスト方針

- **ユニットテスト**: `ConfigManager` がプリセットを正しく読み込むテスト、`--preset` が `PersonaManager.apply_overrides()` に渡るテスト
- **手動確認**: `uv run magi ask --preset arch "テスト"` の動作確認、Claude Code / OpenCode でのスラッシュコマンド発火確認

---

## 将来の拡張

新しいプリセット（例: `/magi:security`、`/magi:ux`）を追加するには:

1. `magi.yaml` の `presets` に新エントリを追加
2. `.claude/skills/magi-<name>/SKILL.md` を1ファイル作成

本体への追加変更は不要。
