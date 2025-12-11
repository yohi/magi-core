# プロダクト概要

MAGI System は 3 賢者（MELCHIOR/BALTHASAR/CASPER）の合議プロセスで多角的な判断を提供する Python 製 CLI ツールです。Core と Plugin を分離し、専門性と拡張性を両立します。

## コア機能
- 合議エンジン（Thinking/Debate/Voting フェーズ）による判定
- 3 ペルソナの思考テンプレートによる多視点分析
- CLI からの質問・仕様生成・レビュー実行（`magi ask` / `magi spec` などのサブコマンド）
- プラグイン拡張（例: `magi-cc-sdd-plugin` で仕様書駆動開発を支援）
- 合議ハードニング: トークン予算管理、構造化出力、クオーラム・ストリーミング制御、サニタイズ/ガード
- 前段 Guardrails + SecurityFilter による二重防御（fail-open/fail-closed を設定で切替）
- プラグイン署名/ハッシュ検証（公開鍵指定とレガシーハッシュ互換を両立）
- Queue ベースのストリーミング出力（TTFB/ドロップを計測しつつバックプレッシャ制御）

## ターゲットユースケース
- コードレビューや設計レビューを多視点で迅速に実施したい開発チーム
- リスク/倫理/実利のバランスを取りたい意思決定プロセス
- 仕様書作成やチェックを自動化したい AI 開発フロー

## 価値/差別化
- Core/Plugin 分離により保守性と拡張性を確保
- 3 賢者モデルで論理・倫理・実利の観点を明示
- CLI ベースで既存ワークフローへ容易に統合
- 合議パイプラインを外部テンプレート/スキーマで管理し、フェイルセーフ時も監査可能なログを提供

## 参考情報
- 必須環境: Python 3.11+, uv
- 主要依存: anthropic, jsonschema, pyyaml, cryptography, hypothesis, pytest
- エントリーポイント: `magi`（`pyproject.toml` の scripts 定義）

updated_at: 2025-12-11
