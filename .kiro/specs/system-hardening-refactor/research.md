# 調査・設計決定ログ

---
**目的**: ディスカバリーフェーズでの調査結果、アーキテクチャ調査、技術設計に関する根拠を記録する。
---

## サマリー
* **機能名**: `system-hardening-refactor`
* **ディスカバリースコープ**: 複合インテグレーション（既存システムの大規模リファクタリング）
* **主要な知見**:
  1. Pydantic は既に使用されておらず、新規導入が必要
  2. `asyncio.Semaphore` および `run_in_executor` は未使用であり、並行処理制御の追加が必要
  3. 既存の `dataclass` ベースの設定モデルを Pydantic V2 へ移行するには、型ヒントの調整が必要

## 調査ログ

### Pydantic V2 の導入方針
* **コンテキスト**: 要件 5（設定値の一元管理）および要件 6（宣言的バリデーション）を満たすための技術選定。
* **参照した情報源**:
  * Pydantic 公式ドキュメント: https://docs.pydantic.dev/latest/
  * `pyproject.toml` の依存関係（現在 Pydantic は未導入）
* **知見**:
  * Pydantic V2 は `BaseSettings` を通じて環境変数・ファイルからの設定ロードと型バリデーションを一体化できる。
  * `field_validator` や `model_validator` を用いて、複雑なクロスフィールドバリデーションを宣言的に記述可能。
  * Python 3.11+ であれば性能面も問題なし。
* **影響**: `Config` を `pydantic.BaseModel` に、`ConfigManager.load` を `Settings.model_validate` に置き換える。既存の `dataclass` は削除し、Pydantic モデルに統一する。

### 非同期 I/O 戦略
* **コンテキスト**: 要件 1（プラグインロードの安定性）において、`PluginLoader.load` が同期的なファイル I/O を実行している。
* **参照した情報源**:
  * Python asyncio ドキュメント: https://docs.python.org/3/library/asyncio-task.html#running-in-threads
  * `aiofiles` ライブラリ: https://github.com/Tinche/aiofiles
* **知見**:
  * `asyncio.to_thread` (Python 3.9+) を使えば、追加の依存なしに同期ブロッキング I/O をスレッドプールにオフロード可能。
  * `aiofiles` は追加依存となるため、依存を増やしたくない場合は `to_thread` が推奨。
* **影響**: `PluginLoader.load` を `async def load` に変更し、ファイル読み込み (`Path.read_text`) と署名検証 (`_verify_security`) を `to_thread` でラップする。

### LLM 同時実行数制御
* **コンテキスト**: 要件 2（LLM 呼び出しの同時実行制御と過負荷耐性）において、`ConsensusEngine` が無制限に `asyncio.gather` を呼び出している。
* **参照した情報源**:
  * Python asyncio Semaphore: https://docs.python.org/3/library/asyncio-sync.html#semaphore
  * Anthropic API Rate Limits
* **知見**:
  * `asyncio.Semaphore` をグローバルまたはエンジン単位で導入し、`send` 呼び出し前に `acquire` することで同時実行数を制御可能。
  * セマフォのカウントは設定可能にし、`MAGI_LLM_CONCURRENCY_LIMIT` などの環境変数で調整可能にする。
* **影響**: `LLMClient` または新規の `ConcurrencyController` クラスにセマフォを導入する。

### DI パターン
* **コンテキスト**: 要件 4（依存性注入によるテスト容易性）において、`ConsensusEngine` が `PersonaManager` / `ContextManager` を直接インスタンス化している。
* **参照した情報源**:
  * 既存コード: `ConsensusEngine.__init__`
  * Pure DI パターン
* **知見**:
  * 現状の規模であれば、DI コンテナ（`dependency-injector` 等）は過剰。
  * コンストラクタ引数に `Optional[PersonaManager]` を追加し、`None` の場合はデフォルト実装を使用する Pure DI パターンで十分。
* **影響**: `ConsensusEngine.__init__` の引数を拡張し、デフォルト引数で後方互換性を維持する。

## アーキテクチャパターン評価

| オプション | 概要 | 利点 | リスク/制限 | 備考 |
|-----------|------|------|------------|------|
| Pure DI (選択) | コンストラクタ引数による依存注入 | シンプル、追加依存なし、テスト容易 | 依存が増えると引数が膨大になる | 現状規模に適合 |
| DI コンテナ | `dependency-injector` 等の導入 | 自動解決、スコープ管理 | 学習コスト、過剰設計 | 将来的な検討対象 |
| Service Locator | グローバル/シングルトンで依存を解決 | 導入が容易 | テスト困難、隠れた依存 | 非推奨 |

## 設計決定

### 決定: Pydantic V2 による設定と入力のスキーマ統一
- **コンテキスト**: 複数箇所に散在する `isinstance` チェックと手動バリデーションを排除し、保守性を向上させたい。
- **検討した選択肢**:
  1. `dataclass` + `jsonschema` で手動検証を継続
  2. Pydantic V2 `BaseModel` に移行
  3. `attrs` + `cattrs` による型付きデシリアライゼーション
- **選択したアプローチ**: Pydantic V2 を採用。`Config`, `PluginMetadata`, `BridgeConfig`, `Plugin` などを `BaseModel` 化する。
- **根拠**: Pydantic V2 は型安全、宣言的バリデーション、優れたエラーメッセージを提供し、Python コミュニティで広く採用されている。
- **トレードオフ**: 新規依存が追加されるが、`jsonschema` の手動スキーマ定義を削減できるため全体的に依存は軽減される方向。
- **フォローアップ**: 既存テストの `dataclass` 前提部分を更新する必要がある。

### 決定: `asyncio.to_thread` による同期 I/O のオフロード
- **コンテキスト**: `aiofiles` を導入するか、標準ライブラリで対応するかの選択。
- **検討した選択肢**:
  1. `aiofiles` ライブラリの導入
  2. `asyncio.to_thread` (Python 3.9+) の使用
- **選択したアプローチ**: `asyncio.to_thread` を使用。追加依存を避け、標準ライブラリのみで対応する。
- **根拠**: Python 3.11+ を前提としており、`to_thread` は十分に成熟している。ファイル I/O は頻繁ではないため、性能差は無視できる。
- **トレードオフ**: 大量の小ファイルを読む場合は `aiofiles` の方が効率的だが、プラグイン数は通常少数であるため問題なし。

### 決定: 本番運用モードのフラグ導入
- **コンテキスト**: 要件 9（公開鍵パス解決の厳格化）において、開発環境のフォールバックを本番で無効化したい。
- **検討した選択肢**:
  1. 環境変数 `MAGI_PRODUCTION_MODE` でフラグを制御
  2. 設定ファイル内のフラグ `production_mode: true`
  3. 両方をサポートし、環境変数を優先
- **選択したアプローチ**: 環境変数 `MAGI_PRODUCTION_MODE` を優先し、設定ファイルでも上書き可能にする。
- **根拠**: 本番デプロイ時に環境変数で強制できるため、設定ファイルの改ざんリスクを軽減できる。

## リスクと軽減策
- **リスク 1**: Pydantic 移行によるテスト破綻 → 段階的に移行し、各コンポーネントごとにテストを更新する。
- **リスク 2**: セマフォ導入によるデッドロック → セマフォのタイムアウトを設定し、監視ログを追加する。
- **リスク 3**: 非同期化による挙動変更 → 既存の同期 API を維持しつつ、内部で `asyncio.run` を呼び出すラッパーを提供する（後方互換性）。

## 参照
- [Pydantic V2 ドキュメント](https://docs.pydantic.dev/latest/) — 設定 / バリデーション設計の参照
- [Python asyncio 公式ガイド](https://docs.python.org/3/library/asyncio.html) — 非同期処理パターン
- [Anthropic API ドキュメント](https://docs.anthropic.com/) — レート制限情報
