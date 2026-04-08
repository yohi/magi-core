# Design Spec: Web UI LLM Integration (Mock to Production)

- **Date**: 2026-04-09
- **Status**: Draft
- **Topic**: Integration of real Magi Core (ConsensusEngine) into Web UI Backend

## 1. Objective
Currently, the Web UI backend uses `MockMagiAdapter` to provide simulated data. This specification defines the design to switch to `ConsensusEngineMagiAdapter`, which executes the actual Magi Core consensus protocol using real LLM clients.

## 2. Architecture Overview
The integration will follow a "Session-based Configuration Injection" pattern.
1. **Frontend**: Collects prompt and optional API keys.
2. **Backend (FastAPI)**: Receives the request and stores API keys in `SessionOptions`.
3. **Adapter (`ConsensusEngineMagiAdapter`)**: 
   - Clones the global `Config`.
   - Merges session-specific API keys and model options.
   - Instantiates `ConsensusEngine`.
   - Transforms `run_stream` events into Web UI-compatible payloads.
4. **Magi Core**: Executes the thinking, debate, and voting phases.

## 3. Data Model Changes

### 3.1 `SessionOptions` (in `src/magi/webui_backend/models.py`)
Add `api_keys` field to allow per-session credentials.

```python
class SessionOptions(BaseModel):
    model: Optional[str] = None
    max_rounds: Optional[int] = None
    timeout_sec: float = 120.0
    attachments: Optional[List[Dict[str, Any]]] = None
    plugin: Optional[Any] = None
    api_keys: Optional[Dict[str, str]] = Field(default_factory=dict) # NEW
```

## 4. Adapter Implementation Details

### 4.1 Configuration Merging
The adapter will merge API keys into the `Config` object used for engine initialization.

```python
# Logic in ConsensusEngineMagiAdapter.run
run_config = copy.deepcopy(self.config)
if options.api_keys:
    # Update global API key or provider-specific keys in run_config
    if "default" in options.api_keys:
        run_config.api_key = options.api_keys["default"]
    # Handle provider-specific mapping if necessary
```

### 4.2 Event Mapping
Mapping `ConsensusEngine` stream types to Web UI types:

| Magi Core Event Type | Payload / Condition | Web UI Event Type | Web UI Target Phase/State |
|----------------------|---------------------|-------------------|--------------------------|
| `event`              | `phase.transition`  | `phase`           | (THINKING, DEBATE, etc.) |
| `stream`             | (persona chunk)     | `unit`            | `state: THINKING/DEBATING`|
| `result`             | (ConsensusResult)   | `final`           | `phase: RESOLVED`        |

## 5. Security Considerations
- **Credential Handling**: API keys provided via Web UI are kept only in memory for the duration of the session and are never logged or persisted to disk.
- **Isolation**: Each session uses a deep copy of the configuration to prevent settings leakage between concurrent requests.

## 6. Testing Strategy
- **Unit Test**: Verify `ConsensusEngineMagiAdapter` correctly transforms a sequence of `ConsensusEngine` events into the expected Web UI JSON format.
- **Integration Test**: Run the Web UI backend with a mock LLM provider (using Magi's existing provider abstraction) to verify the end-to-end flow without hitting real LLM costs.
- **Manual Verification**: Launch the Web UI with a valid API key and verify real-time streaming of Melchior, Balthasar, and Casper's outputs.

## 7. Success Criteria
- [ ] Users can trigger a real LLM execution from the Web UI.
- [ ] Thinking and Debate phases are streamed in real-time.
- [ ] Final decision and voting reasons are displayed correctly upon completion.
- [ ] Errors (e.g., Auth failure) are gracefully handled and displayed in the UI.
