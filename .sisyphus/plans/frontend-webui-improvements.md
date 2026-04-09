# Plan: WebUI Improvements

## Goal
Improve the WebUI by adding a searchable model selector, expanding side panels, persisting settings, and adding a blinking effect to the monolith during deliberation.

## Tasks

### 1. Model Selector with Search (`SettingsModal.tsx`)
- [ ] Add `searchTerm` state to `SettingsModal` component.
- [ ] Add a text input field above the model `<select>` element.
- [ ] Filter `availableModels` based on `searchTerm`.
- [ ] Clear `searchTerm` when the modal is closed or provider is changed.

### 2. Layout Expansion (`styles.css`)
- [ ] Update `.log-panel`, `.control-panel`, and `.result-console` widths.
- [ ] Use `calc((100vw - 1050px) / 2)` (or a similar calculation) to ensure panels reach the center visualizer.
- [ ] Add a `min-width` to ensure the panels remain usable on smaller screens.

### 3. Settings Persistence (`useMagiSession.ts`)
- [ ] Define keys for `localStorage` (e.g., `magi_system_settings`, `magi_unit_settings`).
- [ ] Add `useEffect` to load settings from `localStorage` on component mount.
- [ ] Add `useEffect` to save settings to `localStorage` whenever `systemSettings` or `unitSettings` change.

### 4. Monolith Blinking Effect (`MagiVisualizer.tsx`)
- [ ] Add a `blinking` state or use CSS animation.
- [ ] If `isRunning` is true, trigger a random interval to change the opacity of the `.fill-poly` elements in each monolith.
- [ ] Alternatively, use a CSS `@keyframes` and toggle a class when `isRunning` is true.

## Verification
- [ ] Verify model search works as expected.
- [ ] Verify side panels reach the center on wide screens.
- [ ] Verify settings (API keys, personas) persist after page reload.
- [ ] Verify monoliths blink during deliberation.
