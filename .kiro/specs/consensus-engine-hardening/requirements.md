# 要件ドキュメント

## Introduction
本機能では MAGI の Consensus Engine を性能・信頼性・セキュリティの観点で堅牢化し、合議プロセスの待ち時間とリスクを抑えつつ保守性を高める。トークン予算超過を防ぐための要約・圧縮、ストリーミング応答によるユーザー体験向上、構造化出力とテンプレート外部化による再現性向上、エージェント障害時のクオーラム管理、プロンプト/プラグイン経由の攻撃リスク低減を狙う。

## 要件

### Requirement 1: トークン最適化と応答性
**Objective:** CLI 利用者として、レイテンシとコストを抑えつつ議論・投票結果を迅速に得たいので、コンテキスト膨張を防ぎつつ応答を途切れなく受け取りたい

#### Acceptance Criteria
1. WHEN debate ラウンド終了後に結合コンテキストサイズが `CONSENSUS_TOKEN_BUDGET` (integer, unit: tokens, recommended default: 8192) を超過した場合 THEN Consensus Engine SHALL 議論ログを要約し、次ラウンド以降は要約を元ログの代わりに用いる。
2. IF 投票フェーズの総コンテキスト長が `CONSENSUS_TOKEN_BUDGET` (integer, unit: tokens, recommended default: 8192) を超過する見込みの場合 THEN Consensus Engine SHALL 固定長切り捨てではなく重要度に基づく要約/圧縮を行った上で LLM を呼び出す。
3. WHILE CLI セッションが LLM 出力を待機している間 THE Magi CLI SHALL 生成トークンを到着次第ストリーミング表示し続ける。
4. WHERE コンテキスト削減が発生する場合 THE Consensus Engine SHALL 削減理由と削減後のトークン指標をログに記録する。

### Requirement 2: 構造化出力とプロンプト保守性
**Objective:** 開発者として、LLM 出力の再現性を高めつつプロンプト変更を安全に回せるようにしたいので、構造化出力とテンプレート管理を強化したい

#### Acceptance Criteria
1. WHEN エージェントに投票を要求する場合 THEN Consensus Engine SHALL 定義済みスキーマに従うツールベースの JSON 形式での出力を必須とする。
2. IF 受信した投票ペイロードがスキーマ検証に失敗した場合 THEN Consensus Engine SHALL `CONSENSUS_SUMMARY_RETRY_COUNT` (integer, recommended default: 3, allowable range: 0–10, 0 の場合はリトライなし) 回まで再生成を試み、上限到達時は `CONSENSUS_SCHEMA_RETRY_EXCEEDED` エラーで処理を中断し、WARN ログ `consensus.schema.retry_exhausted retry_count=<count> max=<max> template_version=<ver> payload_id=<id>` と ERROR ログ `consensus.schema.rejected payload_id=<id>` を出力する。
3. WHERE プロンプトテンプレートをコード外で更新する場合 THE Consensus Engine SHALL 外部設定ファイルからテンプレートを読み込み、以下の形式をサポートする: YAML (`.yaml`/`.yml`), JSON (`.json`), Jinja2 (`.j2` 本体 + `.yaml`/`.json` メタデータ)。各形式での必須フィールドは `name` (string), `version` (semver または ISO-8601 timestamp), `schema_ref` (JSON Schema へのパス/URL), `template` (string 本文), `variables` (object, optional) とし、欠落時は検証エラーを返す。
4. WHEN テンプレートを再読み込みする場合 THEN Consensus Engine SHALL バージョン付きタイムスタンプによるキャッシュエントリを採用し、ステージングで検証後にアトミックにスワップする。TTL ベースの無効化 (configurable, recommended default: 300s) を行い、TTL 失効時は自動再読み込みし、また管理 API/CLI により強制リフレッシュを受け付ける。リロード時は INFO ログ `consensus.template.reload reason=<auto|ttl|force> previous=<old> new=<new> ttl=<sec>` を出力する。
5. WHEN テンプレートのホットリロードが発生した場合 THEN 新規リクエストはスワップ直後の新バージョンを即時使用し、処理中のリクエストは開始時のバージョンで完了する。バージョン切り替え時にはイベント/ログ `consensus.template.version_changed old=<old> new=<new> mode=hot-reload` を記録する。
6. WHEN スキーマまたはテンプレートの不整合が検出された場合 THEN Consensus Engine SHALL 影響するテンプレート名とフィールドを含む実行可能なログを出力する。

### Requirement 3: フェイルセーフとクオーラム管理
**Objective:** 運用者として、エージェント障害時でも誤った合議結果を出さないようにしたいので、クオーラムとリトライ挙動を制御したい

#### Acceptance Criteria
1. IF いずれかのフェーズで有効なエージェント数が設定したクオーラムを下回った場合 THEN Consensus Engine SHALL セッションを中断し、CLI にフェイルセーフ状態を返す。
2. WHEN 個別エージェント呼び出しが失敗した場合 THEN Consensus Engine SHALL 設定回数までリトライし、リトライ進行中に有効エージェント数がクオーラム未満に低下した時点でセッションを即時中断し、保持中の「既に取得済みの有効出力」は最終結果として返さずフェイルセーフ応答を返す（部分結果はログに保存する）。上限超過後は当該エージェントを投票から除外した理由を記録する。
3. IF CLI ストリーミング応答の取得が途切れた場合 THEN Magi CLI SHALL `MAGI_CLI_STREAM_RETRY_COUNT` (integer, recommended default: 5) 回までストリーム再接続または再リクエストを試行し、上限到達時はユーザーに失敗理由を通知する。
4. WHEN クオーラム不足による中断が発生した場合 THEN Consensus Engine SHALL 投票結果を出力せず、ユーザー向けに不足状況を示すメッセージを返す。
5. WHILE リトライ処理を進行している間 THE Consensus Engine SHALL 既に取得済みの有効出力を保持し、上書きしない。この「有効出力」は署名/検証/タイムスタンプ等の定義済み有効性基準を満たす個々の出力件数で判定し、クオーラムに部分的に到達した状態では「部分結果フラグ」を付与し、ログおよびユーザーメッセージに反映する。
6. AFTER 個別エージェントのリトライが上限に達した場合 THEN IF クオーラムが満たされているとき THE Consensus Engine SHALL その時点の集計結果を返し、ELSE すべての出力を破棄してフェイルセーフ応答を返す。
7. WHEN フェイルセーフまたは部分結果をユーザーに提示する場合 THEN Magi CLI SHALL 不足理由（クオーラム未達/リトライ上限超過等）、除外したエージェント、保持している部分出力の有無をユーザー向けメッセージに明示し、Consensus Engine SHALL 同一情報を内部ログに記録する。

### Requirement 4: セキュリティ強化
**Objective:** セキュリティ担当として、プロンプトインジェクションやプラグイン経由のコマンドインジェクションを防ぎたいので、入力の境界と検証を強化したい

#### Acceptance Criteria
1. WHERE ユーザー提供テキストをプロンプトに埋め込む場合 THE Consensus Engine SHALL データ領域を明示するマーカーで囲み、付録A「制御シーケンス」の一覧と正規化手順に従いエスケープした上で LLM に送信する。
2. IF ユーザープロンプトや議論コンテキストに付録A「禁止パターン」に定義されたブラックリスト正規表現またはホワイトリスト逸脱が検出された場合 THEN Consensus Engine SHALL 入力を拒否またはサニタイズし、検出パターン識別子を監査ログに残す。
3. WHEN プラグインコマンドを読み込みまたは実行する場合 THEN Plugin Loader SHALL 付録A「シェルメタ文字と検証ルール」に従って引数を検証し、違反時は実行を拒否し検証結果を WARN ログに残す。
4. WHERE プラグインに要求される署名または許可リスト情報が欠落している場合 THE Plugin Loader SHALL 付録A「署名・検証方式」のいずれかを満たさないものとしてプラグインを無効化し、実行前に理由を通知する。
5. IF `CONSENSUS_TOKEN_BUDGET` (integer, unit: tokens, recommended default: 8192) 超過に伴うコンテキスト削減ログに機微情報を含める必要がある場合 THEN Consensus Engine SHALL `LOG_CONTEXT_REDUCTION_KEY` (boolean, recommended default: true) に基づいて削減理由とトークン指標の詳細ログ出力可否を制御し、詳細ログを出力する際も付録Aの制御シーケンスおよび禁止パターンの基準に従いサニタイズする。

##### 付録A: セキュリティ用語集・検証基準
- 制御シーケンス (エスケープ対象と正規化手順):
  - 改行系: `\r`, `\n`, `\r\n` は `\n` に統一。
  - ヌルバイト: `\0` は `\u0000` へエンコードし透過禁止。
  - トークン制御マーカー・プロンプト境界: `{{`, `}}`, `<<`, `>>`, `[[`, `]]` などテンプレート/境界指定子はリテラル化またはバックスラッシュでエスケープ。
  - Unicode 正規化と可視不可視文字: NFC に正規化し、`U+200D` (ZWJ), `U+200C` (ZWNJ), `U+FEFF` (BOM) など不可視結合文字は削除または `\uXXXX` リテラルに置換。
- 禁止パターンと分類 (検出時はパターン名をログ):
  - ブラックリスト例 (regex): `(?i)\bignore\s+all\s+previous\b`, `(?i)\b(system|sys)\s*prompt\b`, `(?s)<\s*script.*?>.*?<\s*/\s*script\s*>`, `(?i)---BEGIN[^\n]{0,40}PRIVATE\s+KEY---`.
  - ホワイトリスト例: `^[A-Za-z0-9_\-.\s,:;"'@/\(\)\[\]]+$` を満たさない場合はサニタイズまたは拒否。
- シェルメタ文字と検証ルール:
  - メタ文字一覧: `$`, `;`, `|`, `>`, `<`, `` ` ``, `&`, `\\`, `*`, `?`, `(`, `)`, `{`, `}`, `[`, `]`, `~`, 改行/タブ。
  - ルール: デフォルトはホワイトリスト (`[A-Za-z0-9_\\-./]`) のみ許可。メタ文字が必要な場合は `shlex.quote` 同等の単一引数クォートを適用し、コマンド連結・リダイレクト・パイプは禁止。空文字・環境変数展開・ワイルドカード展開は無効化する。
- 署名・検証方式 (いずれか必須、詳細実装はセキュリティ実装ガイド参照):
  - HMAC-SHA256: シークレットは環境変数またはシークレットマネージャから取得し、定数時間比較で検証。
  - RSA-PSS: SHA-256 + MGF1(SHA-256)、salt length = hash length、公開鍵は信頼ストアからロード。
  - ハッシュ検証: 取得ファイルの SHA-256 を事前定義値と比較し一致しない場合拒否。
  - 参照: `docs/MAGI-System_Plugin-Based-AI-Driven-Development-Architecture.md.md` のプラグイン安全対策節、またはチーム内セキュリティ実装ガイドライン。

## Configuration
- Requirement 1: `CONSENSUS_TOKEN_BUDGET` (integer, unit: tokens, recommended default: 8192)
- Requirement 2: `CONSENSUS_TOKEN_BUDGET` (integer, unit: tokens, recommended default: 8192), `CONSENSUS_SUMMARY_RETRY_COUNT` (integer, recommended default: 3)
- Requirement 3: `MAGI_CLI_STREAM_RETRY_COUNT` (integer, recommended default: 5)
- Requirement 4: `CONSENSUS_TOKEN_BUDGET` (integer, unit: tokens, recommended default: 8192), `LOG_CONTEXT_REDUCTION_KEY` (boolean, recommended default: true)
