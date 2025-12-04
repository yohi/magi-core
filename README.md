# MAGI System

MAGIシステムは、アニメ「エヴァンゲリオン」に登場するMAGIシステムを、実用的なエンジニアリング・プラットフォームとして再構築するプロジェクトです。

## 概要

3つの異なる人格（MELCHIOR、BALTHASAR、CASPER）による合議プロセスを通じて、より多角的で信頼性の高い判断を提供するPythonベースのCLIツールです。

### 3賢者

- **MELCHIOR-1**: 論理・科学を担当。論理的整合性と事実に基づいた分析を行う
- **BALTHASAR-2**: 倫理・保護を担当。リスク回避と現状維持を優先する
- **CASPER-3**: 欲望・実利を担当。ユーザーの利益と効率を最優先する

## インストール

```bash
# uvを使用したインストール
uv pip install magi
```

## 使用方法

```bash
# 基本的な使用方法
magi <command> [args]

# ヘルプを表示
magi --help

# バージョンを表示
magi --version
```

## 開発

```bash
# 開発環境のセットアップ
uv sync

# テストの実行
uv run python -m unittest discover -s tests -v

# カバレッジ付きテスト
uv run coverage run -m unittest discover -s tests
uv run coverage report
```

## ライセンス

MIT License
