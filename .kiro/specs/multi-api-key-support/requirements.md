# Requirements Document

## Introduction
Anthropic 以外の OpenAI/Gemini など複数プロバイダの API キーと、ClaudeCode/CodexCLI/GeminiCLI/CursorCLI などの CLI 連携を安全に扱うための拡張を行う。

## Requirements

### Requirement 1: 複数プロバイダ鍵の取得・設定
**Objective:** As a MAGI CLI operator, I want to supply provider-specific API keys, so that MAGI が対象プロバイダで合議処理を実行できる。

#### Acceptance Criteria
1. When a provider-specific API key is supplied via environment variable or config, the MAGI CLI shall load the key without requiring other providers’ keys.
2. When multiple provider keys are present, the MAGI CLI shall select the key matching the requested provider context and ignore non-selected keys.
3. If a required provider key is missing for the requested provider, then the MAGI CLI shall reject the request with a clear, actionable error message.
4. While a provider key is cached in process memory, the MAGI CLI shall avoid writing the key to logs, prompts, or events.
5. The MAGI CLI shall allow rotating a provider key at runtime by reloading configuration without restarting the process.

### Requirement 2: プロバイダ選択と実行分離
**Objective:** As a MAGI CLI operator, I want to target a specific provider per invocation, so that合議処理が意図したプロバイダのみで行われる。

#### Acceptance Criteria
1. When a user specifies a provider flag or configuration (e.g., openai/gemini/anthropic), the MAGI CLI shall route LLM calls to the selected provider only.
2. If the selected provider is unsupported or disabled, then the MAGI CLI shall abort execution before contacting any provider.
3. While switching providers between invocations, the MAGI CLI shall isolate credentials and connection settings per provider without cross-contamination.
4. When a provider requires provider-specific parameters (e.g., model name or endpoint), the MAGI CLI shall validate their presence before sending the request.
5. If provider selection is omitted, then the MAGI CLI shall use a documented default provider and surface that choice in the command output.

### Requirement 3: CLI 連携とコマンドガード
**Objective:** As a MAGI CLI operator, I want safe integration with ClaudeCode/CodexCLI/GeminiCLI/CursorCLI bridges, so that外部 CLI 連携も安全に鍵を扱える。

#### Acceptance Criteria
1. When invoking external CLI bridges, the MAGI CLI shall pass only the selected provider’s key and parameters required for that bridge.
2. If an external CLI invocation returns an error related to authentication, then the MAGI CLI shall surface the provider context and actionable remediation in the response.
3. While preparing bridge commands, the MAGI CLI shall validate that no shell metacharacters are present in command or arguments before execution.
4. When a bridge supports multiple providers, the MAGI CLI shall ensure the bridge receives the matching provider identifier alongside the key.
5. If a bridge is not configured for the selected provider, then the MAGI CLI shall fail fast without attempting command execution.

### Requirement 4: 監査・エラー・フェイルセーフ
**Objective:** As a security-conscious operator, I want observable and safe failure modes, so that鍵取り扱いの不備を検知し復旧できる。

#### Acceptance Criteria
1. When a key load or provider selection error occurs, the MAGI CLI shall emit an audit-safe event without including raw key material.
2. If a provider call fails due to invalid credentials, then the MAGI CLI shall stop further retries for that provider and report the failure reason.
3. While Guardrails/SecurityFilter are enabled, the MAGI CLI shall ensure provider selection and key presence are validated before prompt handling.
4. When multiple providers are configured, the MAGI CLI shall allow executing a health-check that verifies each provider key without performing billable operations.
5. If configuration is partially missing (e.g., model set but key absent), then the MAGI CLI shall block execution and direct the user to the missing fields.
