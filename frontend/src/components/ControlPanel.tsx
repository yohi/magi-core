import React from 'react';

interface ControlPanelProps {
  prompt: string;
  setPrompt: (value: string) => void;
  isRunning: boolean;
  onStart: () => void;
  onCancel: () => void;
  onReset: () => void;
  onOpenSystemSettings: () => void; // 追加
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
  onOpenSystemSettings, // 追加
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
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            if (!isRunning) onStart();
          }
        }}
        disabled={isRunning}
      ></textarea>
      <div className="control-actions">
        <div className="btn-group">
          <button 
            id="btn-start" 
            className="btn-start" 
            onClick={onStart} 
            disabled={isRunning} 
            type="button" 
            style={{ flex: 2 }}
          >
            START
          </button>
          <button 
            id="btn-cancel" 
            className="btn-cancel" 
            onClick={onCancel} 
            disabled={!isRunning} 
            type="button" 
            style={{ flex: 1 }}
          >
            CANCEL
          </button>
          <button 
            id="btn-reset" 
            className="btn-reset" 
            onClick={onReset} 
            disabled={!sessionId && !isRunning && phase !== "CANCELLED" && phase !== "ERROR"} 
            type="button" 
            style={{ flex: 1 }}
          >
            RESET
          </button>
        </div>
        <button 
          id="btn-system-settings" 
          className="btn-system-settings" 
          onClick={onOpenSystemSettings} 
          disabled={isRunning} 
          type="button"
        >
          SYSTEM SETTINGS
        </button>
      </div>
    </div>
  );
};
