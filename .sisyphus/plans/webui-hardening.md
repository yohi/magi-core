# WebUI Hardening & Refactoring Plan

## TL;DR

> **Quick Summary**: Current WebUI (MVP) works but carries high technical debt (monolithic frontend, fragile backend coupling, no E2E tests). This plan refactors the frontend into components, decouples the backend adapter by exposing a proper API in `ConsensusEngine`, and establishes a Playwright E2E testing baseline.
>
> **Deliverables**:
> - Refactored Frontend (`components/`, `hooks/`)
> - Safe Backend Adapter (using public `ConsensusEngine` API)
> - E2E Test Suite (Playwright with Mock Mode)
>
> **Estimated Effort**: Medium (Refactoring + Testing)
> **Parallel Execution**: YES (Frontend and Backend tasks are largely independent)
> **Critical Path**: Backend API Update → Adapter Fix → E2E Tests

---

## Context

### Analysis Findings
- **Frontend**: `App.tsx` is a "God Component" (840+ lines) handling UI, WebSocket, and State. Hard to maintain.
- **Backend**: `ConsensusEngineMagiAdapter` relies on private methods (`_run_thinking_phase`), making it fragile to Core updates.
- **Testing**: Zero E2E tests. Reliance on manual verification.

### Metis Consultation
- **Guardrails**: **STRICT UI FREEZE**. No visual design changes. Structural refactoring only.
- **Risks**: Core refactoring might affect CLI. Must use non-breaking additions (e.g., `run_generator`).
- **Missing**: State management strategy. Recommended `useReducer` / Context.

---

## Work Objectives

### Core Objective
Transform the WebUI from a fragile MVP to a maintainable, testable system without changing its external behavior or appearance.

### Concrete Deliverables
1. **Backend**: `ConsensusEngine.run_stream()` (or similar) public generator method.
2. **Backend**: Updated `ConsensusEngineMagiAdapter` using the new public method.
3. **Frontend**: Component library (`StatusPanel`, `LogViewer`, `MagiVisualizer`, `ControlPanel`).
4. **Frontend**: Custom Hook `useMagiSession` isolating WebSocket/State logic.
5. **QA**: `tests/e2e/basic.spec.ts` covering the full session lifecycle using Mock Adapter.

### Definition of Done
- [x] `frontend/src/App.tsx` is reduced to < 200 lines (mainly layout composition).
- [x] Backend Adapter uses NO private methods (`_` prefix) of `ConsensusEngine`.
- [x] `npm run test:e2e` passes in CI/Docker environment.
- [x] UI looks and behaves EXACTLY as before (verified by screenshots).

### Must Have
- **Type Safety**: Full TypeScript strict mode compliance.
- **Backward Compatibility**: CLI behavior must remain unchanged.
- **Mock Mode**: E2E tests must run without hitting real LLM APIs (`MAGI_USE_MOCK=1`).

### Must NOT Have (Guardrails)
- **Visual Changes**: No CSS tweaks, no new animations, no layout changes.
- **New Features**: No authentication, no history persistence, no multi-user support.
- **Core Rewrites**: Do not change the logic of `ConsensusEngine`, only expose it.

---

## Verification Strategy (MANDATORY)

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
> ALL tasks in this plan MUST be verifiable WITHOUT any human action.

### Test Decision
- **Infrastructure exists**: YES (Backend: unittest, Frontend: Vite/None)
- **Automated tests**:
  - **Backend**: `unittest` for new Engine method.
  - **Frontend**: Component tests (optional/skipped for MVP refactor), reliance on E2E.
  - **E2E**: Playwright (New setup).

### Agent-Executed QA Scenarios

**1. Backend API Verification**
```
Scenario: ConsensusEngine stream method yields events
  Tool: Bash (python)
  Preconditions: Virtual environment active
  Steps:
    1. Create script `verify_engine.py` importing ConsensusEngine
    2. Run engine with `run_stream()` and mock config
    3. Assert it yields phases (THINKING, DEBATE, VOTING)
    4. Assert final result is returned
  Expected Result: Script exits with code 0
  Evidence: Output of python script
```

**2. Frontend Refactor Verification (Visual Regression)**
```
Scenario: UI looks identical after refactor
  Tool: Playwright (playwright skill)
  Preconditions: WebUI running on localhost:3000 (Mock Mode)
  Steps:
    1. Navigate to /
    2. Wait for .magi-container
    3. Screenshot `after-refactor.png`
    4. Compare with reference screenshot (if available) or manual check instruction
    *Since we don't have reference images yet, we assert structure*
    5. Assert .monolith.melchior exists
    6. Assert .panel.log-panel exists
  Expected Result: All UI elements present
  Evidence: Screenshot
```

**3. E2E Full Flow Verification**
```
Scenario: Start to Finish (Mock Mode)
  Tool: Playwright (playwright skill)
  Preconditions: Docker compose up (Mock Mode)
  Steps:
    1. Navigate to /
    2. Fill #prompt-input with "Test Prompt"
    3. Click #btn-start
    4. Wait for #phase-txt to contain "THINKING"
    5. Wait for #phase-txt to contain "RESOLVED" (timeout: 30s)
    6. Assert #result-console is visible
  Expected Result: Session completes successfully
  Evidence: .sisyphus/evidence/e2e-flow.png
```

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Backend Core & Test Setup):
├── Task 1: Expose ConsensusEngine Streaming API
└── Task 5: Setup Playwright E2E Scaffold

Wave 2 (Refactoring):
├── Task 2: Update Adapter to use Public API (Depends on 1)
├── Task 3: Extract Frontend Components (Independent)
└── Task 4: Extract Frontend Logic to Hook (Depends on 3)

Wave 3 (Integration & Verification):
└── Task 6: Run E2E Tests & Fix Regressions (Depends on 2, 4, 5)
```

---

## TODOs

- [x] 1. Expose ConsensusEngine Streaming API

  **What to do**:
  - Modify `src/magi/core/consensus.py`.
  - Add `run_stream(prompt)` (or similar) generator method.
  - This method should yield `StreamChunk` or similar events for each phase transition and log.
  - Ensure it calls the existing logic but pauses/yields appropriately.
  - Add unit test `tests/unit/test_consensus_streaming.py`.

  **Recommended Agent**: `ultrabrain` (Python logic)

  **Acceptance Criteria**:
  - [x] `ConsensusEngine` has a public generator method.
  - [x] Unit test confirms it yields events without error.
  - [x] Existing `run()` method still works (calls streaming method internally or shares logic).

- [x] 2. Update Adapter to use Public API

  **What to do**:
  - Modify `src/magi/webui_backend/adapter.py`.
  - Update `ConsensusEngineMagiAdapter` to iterate over the new `ConsensusEngine` generator.
  - Remove all usages of private methods (`_run_thinking_phase`, etc.).

  **Recommended Agent**: `quick` (Python)

  **Acceptance Criteria**:
  - [x] `adapter.py` contains zero `._` method calls on engine instance.
  - [x] `run_session_task` still broadcasts events correctly (verified via verify script/tests).

- [x] 3. Extract Frontend Components

  **What to do**:
  - Create `frontend/src/components/`.
  - Extract:
    - `MagiVisualizer.tsx` (The 3 units SVG + Center)
    - `StatusPanel.tsx` (Phase, Progress, Header)
    - `LogPanel.tsx` (Log list)
    - `ResultConsole.tsx` (Final decision)
    - `ControlPanel.tsx` (Input + Buttons)
    - `SettingsModal.tsx`
  - Update `App.tsx` to import these.

  **Recommended Agent**: `visual-engineering` (React)

  **Acceptance Criteria**:
  - [x] `App.tsx` logic is simplified (rendering only).
  - [x] App builds successfully (`npm run build`).
  - [x] UI appearance is unchanged.

- [x] 4. Extract Frontend Logic to Hook

  **What to do**:
  - Create `frontend/src/hooks/useMagiSession.ts`.
  - Move `WebSocket` logic, event handling, and state (`phase`, `logs`, `units`) into the hook.
  - Use `useReducer` for state management (cleaner than multiple `useState`).
  - `App.tsx` calls `const { state, actions } = useMagiSession();`.

  **Recommended Agent**: `visual-engineering` (React Logic)

  **Acceptance Criteria**:
  - [x] `App.tsx` has minimal state logic.
  - [x] WebSocket connection/reconnection works via the hook.

- [x] 5. Setup Playwright E2E Scaffold

  **What to do**:
  - Initialize Playwright in `tests/e2e/` (or root `e2e/` if preferred, but keeping in `tests` is better for python repo).
  - Create `playwright.config.ts`.
  - Create `tests/e2e/mock_session.spec.ts`.
  - Configure `npm script` or `uv run` command to run it.

  **Recommended Agent**: `quick` (Config/Setup)

  **Acceptance Criteria**:
  - [x] Playwright installed and configured.
  - [x] Simple test "opens page" passes.

- [x] 6. Run E2E Tests & Fix Regressions

  **What to do**:
  - Implement full scenario in `mock_session.spec.ts`.
  - Run against the refactored Frontend + Backend.
  - Fix any bugs found.

  **Recommended Agent**: `auto` (Testing/Fixing)

  **Acceptance Criteria**:
  - [x] Full session (Mock Mode) passes automatically.
  - [x] Cancel session passes.
  - [x] UI elements are correctly identified by selectors.

---

## Success Criteria

### Verification Commands
```bash
# Backend Test
uv run python -m unittest tests/unit/test_consensus_streaming.py

# Frontend Build
cd frontend && npm run build

# E2E Test
npx playwright test
```

### Final Checklist
- [x] Frontend code is modular and typed.
- [x] Backend Adapter is "clean" (no private access).
- [x] CI pipeline (or local equivalent) can run E2E tests.
- [x] No visual regression.
