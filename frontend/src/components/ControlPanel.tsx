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
        disabled={isRunning}
      ></textarea>
      <div className="control-actions" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div className="btn-group" style={{ display: 'flex', gap: '10px' }}>
          <button id="btn-start" onClick={onStart} disabled={isRunning} type="button" style={{ flex: 2 }}>
            START
          </button>
          <button id="btn-cancel" onClick={onCancel} disabled={!isRunning} type="button" style={{ flex: 1 }}>
            CANCEL
          </button>
          <button id="btn-reset" onClick={onReset} disabled={!sessionId && !isRunning && phase !== "CANCELLED" && phase !== "ERROR"} type="button" style={{ flex: 1 }}>
            RESET
          </button>

        </div>
        <button 
          className="secondary" 
          id="btn-system-settings" 
          onClick={onOpenSystemSettings} 
          disabled={isRunning} 
          type="button"
          style={{ 
            width: '100%', 
            fontSize: '12px', 
            padding: '6px', 
            border: '1px solid var(--magi-blue)',
            color: 'var(--magi-blue)',
            background: 'transparent'
          }}
        >
          SYSTEM SETTINGS
        </button>
      </div>
    </div>
  );
};
