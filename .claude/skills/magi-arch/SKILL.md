---
name: magi-arch
description: MAGIシステムをアーキテクチャレビュー人格（システムアーキテクト・リードエンジニア・クリエイター）で起動し、設計判断の合議を得る。技術設計・アーキテクチャの是非を多角的に判断したいとき、あるいはユーザーが /magi-arch と入力したときに使う。
disable-model-invocation: true
---

# MAGI System — arch プリセット

## 実行手順

1. `$ARGUMENTS` をユーザーの質問として受け取る
2. プロジェクトルートで以下を実行する:
   `uv run magi ask --preset arch "$ARGUMENTS"`
3. 標準出力の合議結果をそのままチャットに返す

## 注意事項

- 質問は必須。空の場合はユーザーに質問内容を求める
- `uv` が PATH にない場合は `python -m magi ask --preset arch "$ARGUMENTS"` を試みる
- arch プリセットは組込み（`BUILTIN_PRESETS`）のためクローン直後から動作する
- 実行にはプロジェクトルートの `magi.yaml`、または環境変数 `MAGI_ANTHROPIC_API_KEY` など利用プロバイダの API キーが必要
- `magi.yaml` の `presets.arch` を定義すると人格を上書きできる
- 終了コード: 0=APPROVE, 1=DENY, 2=CONDITIONAL
