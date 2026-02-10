# MAGI System — Agent Guidelines

Python CLI tool providing multi-perspective judgment through a consensus process of three Magi
(MELCHIOR/BALTHASAR/CASPER). Core and Plugin are separated; multi-provider LLM support
(Anthropic, OpenAI, Gemini).

## Language Policy

- **All responses, documentation, comments, docstrings, and commit messages MUST be in Japanese.**
- Markdown content (requirements.md, design.md, tasks.md, etc.) must also be in Japanese.
- Technical terms, commands, and international standards (protocol names, etc.) may remain in English.

## Environment

- **Python**: 3.11+
- **Package manager**: `uv` (required)
- **Build backend**: `hatchling`
- **Test framework**: `unittest` (property-based tests with `hypothesis`)
- **Linter/Formatter**: None configured (no ruff, mypy, black, etc.)

## Commands

### Setup
```bash
uv sync                    # Install/sync dependencies
uv add <package_name>      # Add a package
uv run magi --help         # Verify installation
```

### Testing
**Important**: Always run relevant tests after making changes.
```bash
# All tests
uv run python -m unittest discover -s tests -v

# By category
uv run python -m unittest discover -s tests/unit -v
uv run python -m unittest discover -s tests/property -v
uv run python -m unittest discover -s tests/integration -v

# Single file
uv run python -m unittest tests/unit/test_cli.py

# Single test case (most frequently used)
uv run python -m unittest tests.unit.test_cli.TestArgumentParser.test_parse_help_short
```

### Coverage
```bash
uv run coverage run -m unittest discover -s tests
uv run coverage report
uv run coverage html
```

## Directory Structure

```
src/magi/
├── __main__.py              # CLI entry point (magi command)
├── models.py                # Shared data models (dataclass, Enum)
├── errors.py                # Error codes & exception hierarchy
├── agents/                  # Persona & agents (think/debate/vote)
├── cli/                     # Argument parser & CLI bootstrap
├── config/                  # Config management (Pydantic V2 BaseSettings)
│   └── settings.py          # MagiSettings (env vars / .env / magi.yaml)
├── core/                    # Consensus engine & hardening
│   ├── consensus.py         # ConsensusEngine (async, Thinking/Debate/Voting)
│   ├── concurrency.py       # ConcurrencyController (asyncio.Semaphore)
│   ├── streaming.py         # QueueStreamingEmitter
│   └── token_budget.py, quorum.py, schema_validator.py, template_loader.py
├── llm/                     # LLM adapters (Anthropic/OpenAI/Gemini)
│   └── auth/                # Auth (OAuth, Copilot, Claude)
├── output/                  # Output formatters
├── plugins/                 # Plugin system (loader/executor/guard/bridge/signature)
├── security/                # SecurityFilter, GuardrailsAdapter
└── webui_backend/           # FastAPI WebUI backend (Preview)
tests/
├── unit/                    # Unit tests
├── property/                # Property-based tests (Hypothesis)
└── integration/             # Integration tests
```

## Code Style

### Import Order
1. Standard library (`import os`, `from typing import ...`)
2. Third-party (`import anthropic`, `from pydantic import ...`)
3. Local (`from magi.core import ...`) — **absolute imports** with `magi.` prefix

### Docstrings
- Written in **Japanese**. Use triple quotes `"""`. Follow Google Style.
- Format: summary line → blank line → details → `Args/Returns/Raises`
```python
def create_config_error(message: str, details: Optional[Dict[str, Any]] = None) -> MagiError:
    """設定エラーを作成

    Args:
        message: エラーメッセージ
        details: 追加詳細

    Returns:
        MagiError: 設定エラー
    """
```

### Type Hints
- **Required** on all function arguments and return values.
- Use `typing` module (`List`, `Dict`, `Optional`, `Any`, `Protocol`).
- In Pydantic models, use `Field()` with explicit validation constraints.

### Naming Conventions
| Target | Convention | Example |
|--------|------------|---------|
| Files/Modules | `snake_case` | `consensus_engine.py` |
| Classes | `CamelCase` | `ConsensusEngine` |
| Functions/Methods/Variables | `snake_case` | `execute_voting_process` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT` |
| Enum members | `UPPER_SNAKE_CASE` | `Vote.APPROVE` |

### Data Model Selection
| Purpose | Choice | Example |
|---------|--------|---------|
| Simple data structures | `dataclasses.dataclass` | `MagiError`, `VotingTally`, `ThinkingOutput` |
| Enumerations | `enum.Enum` | `Vote`, `Decision`, `PersonaType`, `ErrorCode` |
| Config with validation | `pydantic.BaseModel` | `LLMConfig`, `PersonaConfig` |
| Env-var-integrated config | `pydantic_settings.BaseSettings` | `MagiSettings` |
| Interface definitions | `typing.Protocol` | `VotingStrategy`, `TokenBudgetManagerProtocol` |

### Async Patterns
- The consensus engine (`consensus.py`) is `asyncio`-based. Use `async def` / `await`.
- Concurrency control goes through `ConcurrencyController` (`asyncio.Semaphore`).
- I/O-bound operations (LLM calls, etc.) are parallelized with `asyncio.gather`.
- Use `contextlib` for async context management where appropriate.

### Logging
```python
import logging
logger = logging.getLogger(__name__)
```
- Define `logger` at module level using `__name__`.

### Error Handling
- Custom exceptions are hierarchically defined in `magi.errors`:
  - `MagiException` (base) → `ValidationException` → `PluginValidationException`
  - `MagiException` → `SecurityException` → `GuardrailsTimeoutException` / `GuardrailsModelException`
  - `MagiException` → `RetryableException`
- Use factory functions to create errors: `create_config_error()`, `create_api_error()`, `create_plugin_error()`, `create_agent_error()`
- User-facing error messages should be in **Japanese**.

### Public API
- `models.py` uses `__all__` to declare public symbols. Add new models to `__all__` when created.

### Writing Tests
- Inherit from `unittest.TestCase`. Add Japanese docstrings to test classes and methods.
- Use `unittest.mock.patch` / `MagicMock` for mocking.
- In `tests/property/`, use `hypothesis` with `@given` + `st.` strategies.
```python
class TestArgumentParser(unittest.TestCase):
    """ArgumentParserのユニットテスト"""
    def setUp(self):
        """テストの準備"""
        self.parser = ArgumentParser()
    def test_parse_help_short(self):
        """短縮形ヘルプオプションのパース"""
        result = self.parser.parse(["-h"])
        self.assertTrue(result.options.get("help"))
```

## Spec-Driven Development (SDD)
- `.kiro/steering/`: Project-wide policies (tech stack, structure, product direction)
- `.kiro/specs/`: Per-feature specs (requirements.md → design.md → tasks.md)
- 3-phase approval: Requirements → Design → Tasks → Implementation

## Instructions for Agents

1. **Review existing patterns before implementing**: Follow Japanese docstrings, type hints, and dataclass/Pydantic conventions.
2. **Test-driven**: Create test cases first when adding features; verify with single-test execution as you go.
3. **Always run related tests after changes**: Confirm nothing is broken before marking work complete.
4. **Act autonomously**: Gather context yourself and work toward task completion. Ask questions when unclear.
