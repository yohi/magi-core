import React from "react";
import { Decision } from "../types";

interface StatusPanelProps {
  phase: string;
  progress: number;
  decision: Decision | null;
  serverMode: string;
}

export const StatusPanel: React.FC<StatusPanelProps> = ({
  phase,
  progress,
  decision,
  serverMode,
}) => {
  const phaseColor =
    decision === "APPROVE"
      ? "var(--magi-blue)"
      : decision === "DENY" || phase === "ERROR" || phase === "CANCELLED"
      ? "var(--magi-red)"
      : "var(--magi-orange)";

  return (
    <div className="status-bar">
      {serverMode === "mock" && (
        <div
          style={{
            backgroundColor: "var(--magi-orange)",
            color: "black",
            padding: "2px 8px",
            marginRight: "10px",
            fontWeight: "bold",
            fontSize: "0.8rem",
          }}
        >
          MOCK MODE
        </div>
      )}
      <div className="phase-indicator" style={{ color: phaseColor }}>
        PHASE: <span id="phase-txt">{phase}</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${Math.min(Math.max(progress, 0), 100)}%` }}></div>
      </div>
    </div>
  );
};
