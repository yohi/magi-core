import { useState, useCallback, useRef, useEffect } from "react";
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
  
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

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
      const rawTemp = Number(next[currentEditingUnit].temp);
      const safeTemp = Number.isFinite(rawTemp)
        ? Math.min(1, Math.max(0, rawTemp))
        : 0.5;
      next[currentEditingUnit] = {
        ...next[currentEditingUnit],
        temp: safeTemp,
      };
      
      addLog(`UPDATED ${next[currentEditingUnit].name}`, "info");
      return next;
    });
    
    closeModal();
  }, [currentEditingUnit, setUnitSettings, addLog, closeModal]);

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

        <LogPanel logs={logs} ref={logRef} />

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

