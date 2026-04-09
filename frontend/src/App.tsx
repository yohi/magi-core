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
    systemSettings,
    modelDefinitions,
  } = state;
  const {
    setPrompt,
    setUnitSettings,
    setSystemSettings,
    startSequence,
    handleCancel,
    resetSequence,
    addLog
  } = actions;

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentEditingUnit, setCurrentEditingUnit] = useState<
    "melchior" | "balthasar" | "casper" | "system" | null
  >(null);
  
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  const openModal = useCallback((unitKey: "melchior" | "balthasar" | "casper" | "system") => {
    setCurrentEditingUnit(unitKey);
    setIsModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setIsModalOpen(false);
    setCurrentEditingUnit(null);
  }, []);

  const saveSettings = useCallback(() => {
    if (!currentEditingUnit) return;
    
    if (currentEditingUnit === 'system') {
      addLog("SYSTEM SETTINGS UPDATED", "info");
    } else {
      const unitName = unitSettings[currentEditingUnit].name;
      addLog(`UPDATED ${unitName}`, "info");
    }
    closeModal();
  }, [currentEditingUnit, unitSettings, addLog, closeModal]);

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
          onOpenSystemSettings={() => openModal('system')}
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
        systemSettings={systemSettings}
        setSystemSettings={setSystemSettings}
        modelDefinitions={modelDefinitions}
        saveSettings={saveSettings}
        closeModal={closeModal}
      />
    </div>
  );
}

