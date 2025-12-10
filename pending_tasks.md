# 残課題・改善点まとめ

- `ask` コマンド未実装で ConsensusEngine 未統合。`magi ask` が常に未実装エラー。
- `spec` コマンドの 3 賢者レビュー統合が未完。cc-sdd 実行後に「開発中」表示のみ。
- SecurityFilter の `removed_patterns` が常に空で、禁止パターン除去の監査ログが残らない。
- 投票ペイロード検証が手書きのみで jsonschema + リトライのフェイルセーフ未整備。
- トークン予算圧縮が単純セグメント選択のみで要約ステップなし。削減ログ精度も限定的。
- `.kiro/specs/magi-core/spec.json` の remaining_tasks=7 が tasks.md 全完了と不整合。メタ情報更新が必要。
- プラグインローダーのプロパティテストが `.disabled` で無効化され CI で走っていない。

