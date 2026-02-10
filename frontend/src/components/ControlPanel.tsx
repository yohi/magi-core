import React from 'react';

interface ControlPanelProps {
  prompt: string;
  setPrompt: (value: string) => void;
  isRunning: boolean;
  onStart: () => void;
  onCancel: () => void;
  onReset: () => void;
  sessionId: string | null;
  phase: string;
}

export const ControlPanel: React.FC<ControlPanelProps> = ({
  prompt,
  setPrompt,
  isRunning,
  onStart,
  onCancel,
  onReset,
  sessionId,
  phase,
}) => {
  return (
    <div className="panel control-panel">
      <textarea
        id="prompt-input"
        placeholder="ENTER PROMPT DATA..."
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        disabled={isRunning}
      ></textarea>
      <div className="btn-group">
        <button id="btn-start" onClick={onStart} disabled={isRunning} type="button">
          START
        </button>
        <button id="btn-cancel" onClick={onCancel} disabled={!isRunning} type="button">
          CANCEL
        </button>
        <button id="btn-reset" onClick={onReset} disabled={!sessionId && !isRunning && phase !== "CANCELLED"} type="button">
          RESET
        </button>
      </div>
    </div>
  );
};
