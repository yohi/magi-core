# AI-DLC and Spec-Driven Development

Kiro-style Spec Driven Development implementation on AI-DLC (AI Development Life Cycle)

## Project Memory
Project memory keeps persistent guidance (steering, specs notes, component docs) so Codex honors your standards each run. Treat it as the long-lived source of truth for patterns, conventions, and decisions.

- Use `.kiro/steering/` for project-wide policies: architecture principles, naming schemes, security constraints, tech stack decisions, api standards, etc.
- Use local `AGENTS.md` files for feature or library context (e.g. `src/lib/payments/AGENTS.md`): describe domain assumptions, API contracts, or testing conventions specific to that folder. Codex auto-loads these when working in the matching path.
- Specs notes stay with each spec (under `.kiro/specs/`) to guide specification-level workflows.

## Project Context

### Paths
- Steering: `.kiro/steering/`
- Specs: `.kiro/specs/`

### Steering vs Specification

**Steering** (`.kiro/steering/`) - Guide AI with project-wide rules and context
**Specs** (`.kiro/specs/`) - Formalize development process for individual features

### Active Specifications
- Check `.kiro/specs/` for active specifications
- Use `/prompts:kiro-spec-status [feature-name]` to check progress

## Development Guidelines
- **Language Policy**: ALWAYS respond in Japanese. Think in English for technical precision, but ALL outputs (responses, documentation, comments, commit messages) MUST be in Japanese unless explicitly requested otherwise.
- All Markdown content written to project files (e.g., requirements.md, design.md, tasks.md, research.md, validation reports) MUST be written in Japanese.
- Code comments SHOULD be in Japanese for better readability.
- Git commit messages SHOULD be in Japanese.

## Minimal Workflow
- Phase 0 (optional): `/prompts:kiro-steering`, `/prompts:kiro-steering-custom`
- Phase 1 (Specification):
  - `/prompts:kiro-spec-init "description"`
  - `/prompts:kiro-spec-requirements {feature}`
  - `/prompts:kiro-validate-gap {feature}` (optional: for existing codebase)
  - `/prompts:kiro-spec-design {feature} [-y]`
  - `/prompts:kiro-validate-design {feature}` (optional: design review)
  - `/prompts:kiro-spec-tasks {feature} [-y]`
- Phase 2 (Implementation): `/prompts:kiro-spec-impl {feature} [tasks]`
  - `/prompts:kiro-validate-impl {feature}` (optional: after implementation)
- Progress check: `/prompts:kiro-spec-status {feature}` (use anytime)

## Development Rules
- 3-phase approval workflow: Requirements → Design → Tasks → Implementation
- Human review required each phase; use `-y` only for intentional fast-track
- Keep steering current and verify alignment with `/prompts:kiro-spec-status`
- Follow the user's instructions precisely, and within that scope act autonomously: gather the necessary context and complete the requested work end-to-end in this run, asking questions only when essential information is missing or the instructions are critically ambiguous.

## Steering Configuration
- Load entire `.kiro/steering/` as project memory
- Default files: `product.md`, `tech.md`, `structure.md`
- Custom files are supported (managed via `/prompts:kiro-steering-custom`)

---

# Technical Standards & Commands

## Environment
- **Python**: 3.11+
- **Manager**: `uv` (required for dependency management)

## Key Commands

### Setup
```bash
uv sync
```

### Testing
This project uses `unittest` as the primary framework.

**Run All Tests:**
```bash
uv run python -m unittest discover -s tests -v
```

**Run Specific Test File:**
```bash
uv run python -m unittest tests/unit/test_cli.py
```

**Run Specific Test Case:**
```bash
# Format: path.to.module.Class.method
uv run python -m unittest magi.tests.unit.test_cli.TestArgumentParser.test_parse_help_short
```

**Coverage:**
```bash
uv run coverage run -m unittest discover -s tests
uv run coverage report
```

## Code Style Guidelines

### Language & Documentation
- **Docstrings**: MUST be in **Japanese**.
  - Use triple quotes `"""` for docstrings.
  - Structure: Brief summary line, blank line, detailed description.
- **Comments**: MUST be in **Japanese**.
- **Commit Messages**: MUST be in **Japanese**.

### Type Hinting
- **Strict Typing**: Use type hints for ALL function arguments and return values.
- Use `typing` module (`List`, `Dict`, `Any`, `Optional`) or modern union syntax (`str | None`) where supported.

### Naming Conventions
- **Files/Modules**: `snake_case` (e.g., `consensus_engine.py`)
- **Classes**: `CamelCase` (e.g., `ConsensusEngine`)
- **Functions/Methods**: `snake_case` (e.g., `execute_voting_process`)
- **Variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`

### Architecture & Patterns
- **Imports**:
  1. Standard Library
  2. Third-party Libraries
  3. Local Application Imports (absolute imports preferred, e.g., `from magi.core import ...`)
- **Error Handling**:
  - Use specific exceptions defined in `magi.core.errors` where applicable.
  - Fail gracefully with clear error messages (in Japanese).

### Testing Standards
- Place tests in `tests/` directory mirroring source structure.
- Use `unittest.TestCase`.
- Mock external dependencies (LLM calls, File I/O).
