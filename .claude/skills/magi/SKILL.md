---
name: magi
description: MAGIシステムの3賢者（科学者・母親・女としての赤木ナオコ）に質問して合議判定を得る。多角的な判断が必要なとき、あるいはユーザーが /magi と入力したときに使う。
disable-model-invocation: true
---

# MAGI System — デフォルトプリセット

## 実行手順

1. `$ARGUMENTS` をユーザーの質問として受け取る
2. プロジェクトルートで以下を実行する:
   `uv run magi ask "$ARGUMENTS"`
3. 標準出力の合議結果をそのままチャットに返す

## 注意事項

- 質問は必須。空の場合はユーザーに質問内容を求める
- `uv` が PATH にない場合は `python -m magi ask "$ARGUMENTS"` を試みる
- 実行にはプロジェクトルートの `magi.yaml`、または環境変数 `MAGI_ANTHROPIC_API_KEY` が必要
- 終了コード: 0=APPROVE, 1=DENY, 2=CONDITIONAL
