import { useState, useCallback } from "react";
import { useMagiSession } from "./hooks/useMagiSession";
import { StatusPanel } from "./components/StatusPanel";
import { LogPanel } from "./components/LogPanel";
import { ResultConsole } from "./components/ResultConsole";
import { ControlPanel } from "./components/ControlPanel";
import { SettingsModal } from "./components/SettingsModal";
import { MagiVisualizer } from "./components/MagiVisualizer";

export default function App() {
  const { state, actions } = useMagiSession();
  const {
    prompt,
    phase,
    progress,
    decision,
    finalResult,
    logs,
    unitStates,
    activeUnit,
    isRunning,
    sessionId,
    serverMode,
    unitSettings,
  } = state;
  const {
    setPrompt,
    setUnitSettings,
    startSequence,
    handleCancel,
    resetSequence,
    addLog
  } = actions;

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentEditingUnit, setCurrentEditingUnit] = useState<
    "melchior" | "balthasar" | "casper" | null
  >(null);

  const openModal = useCallback((unitKey: "melchior" | "balthasar" | "casper") => {
    setCurrentEditingUnit(unitKey);
    setIsModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setIsModalOpen(false);
    setCurrentEditingUnit(null);
  }, []);

  const saveSettings = useCallback(() => {
    if (!currentEditingUnit) return;
    
    setUnitSettings((prev) => {
      const next = { ...prev };
      const rawTemp = next[currentEditingUnit].temp;
      const safeTemp = Number.isNaN(rawTemp) ? 0.5 : Math.min(1, Math.max(0, rawTemp));
      next[currentEditingUnit] = {
        ...next[currentEditingUnit],
        temp: safeTemp,
      };
      return next;
    });
    
    addLog(`UPDATED ${unitSettings[currentEditingUnit].name}`, "info");
    closeModal();
  }, [currentEditingUnit, unitSettings, setUnitSettings, addLog, closeModal]);

  return (
    <div className="app-root">
      <MagiVisualizer
        activeUnit={activeUnit}
        unitStates={unitStates}
        openModal={openModal}
        phase={phase}
        decision={decision}
        isRunning={isRunning}
      />

      <div className="dashboard-ui">
        <StatusPanel
          phase={phase}
          progress={progress}
          decision={decision}
          serverMode={serverMode}
        />

        <LogPanel logs={logs} />

        <ResultConsole finalResult={finalResult} />

        <ControlPanel
          prompt={prompt}
          setPrompt={setPrompt}
          onStart={startSequence}
          onCancel={handleCancel}
          onReset={resetSequence}
          isRunning={isRunning}
          sessionId={sessionId}
          phase={phase}
        />
      </div>

      <SettingsModal
        isOpen={isModalOpen}
        currentEditingUnit={currentEditingUnit}
        unitSettings={unitSettings}
        setUnitSettings={setUnitSettings}
        saveSettings={saveSettings}
        closeModal={closeModal}
      />
    </div>
  );
}

