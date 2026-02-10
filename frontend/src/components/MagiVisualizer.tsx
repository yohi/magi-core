import React, { useEffect, useRef } from "react";
import { UnitKey, UnitState, Decision } from "../types";

interface MagiVisualizerProps {
  activeUnit: UnitKey | null;
  unitStates: Record<UnitKey, UnitState>;
  openModal: (key: "melchior" | "balthasar" | "casper") => void;
  phase: string;
  decision: Decision | null;
  isRunning: boolean;
}

export const MagiVisualizer: React.FC<MagiVisualizerProps> = ({
  activeUnit,
  unitStates,
  openModal,
  phase,
  decision,
  isRunning,
}) => {
  const scalerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleResize = () => {
      if (!scalerRef.current) return;
      const scaleX = window.innerWidth / 1100;
      const scaleY = window.innerHeight / 800;
      const scale = Math.min(scaleX, scaleY, 1.2);
      scalerRef.current.style.transform = `scale(${scale})`;
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const getUnitClass = (unit: UnitKey) => {
    const state = unitStates[unit];
    if (state === "THINKING") return "unit-thinking";
    if (state === "DEBATING") return "unit-debating";
    if (state === "VOTING") return "unit-voting";
    if (state === "VOTED") return "unit-voted";
    return "";
  };

  const showThinkingStamp = decision === null && isRunning;
  const showApproveStamp = decision === "APPROVE";
  const showDenyStamp = decision === "DENY";
  const showCancelledStamp = phase === "CANCELLED";

  return (
    <div className="scale-wrapper" id="scaler" ref={scalerRef}>
      <div className={`magi-container ${phase === "THINKING" ? "thinking" : ""}`} id="magi-system">
        <div className="info-block left">
          <div className="green-line"></div>
          <div className="header-title">
            <span>提</span>
            <span>訴</span>
          </div>
          <div className="green-line"></div>
          <div className="data-list">
            <span className="code-highlight">CODE : 378</span>
            <div className="data-row">FILE:MAGI_SYS</div>
            <div className="data-row">EXTENTION:6008</div>
            <div className="data-row">EX_MODE:OFF</div>
            <div className="data-row">PRIORITY:AAA</div>
          </div>
        </div>

        <div className="info-block right">
          <div className="green-line"></div>
          <div className="header-title">
            <span>決</span>
            <span>議</span>
          </div>
          <div className="green-line"></div>
          <div className="hiketsu-container">
            <div
              id="stamp-thinking"
              className={`stamp stamp-thinking ${showThinkingStamp ? "visible" : ""}`}
              style={{ display: showThinkingStamp ? "flex" : "none" }}
            >
              <span>審議中</span>
            </div>
            <div
              id="stamp-deny"
              className={`stamp stamp-deny ${showDenyStamp ? "visible" : ""}`}
              style={{ display: showDenyStamp ? "flex" : "none" }}
            >
              <span>否決</span>
            </div>
            <div
              id="stamp-cancelled"
              className={`stamp stamp-cancelled ${showCancelledStamp ? "visible" : ""}`}
              style={{ display: showCancelledStamp ? "flex" : "none" }}
            >
              <span>中止</span>
            </div>
            <div
              id="stamp-approve"
              className={`stamp stamp-approve ${showApproveStamp ? "visible" : ""}`}
              style={{ display: showApproveStamp ? "flex" : "none" }}
            >
              <span>可決</span>
            </div>
          </div>
        </div>

        <div className="connector conn-horizontal"></div>
        <div className="connector conn-diag-left"></div>
        <div className="connector conn-diag-right"></div>

        <svg className="geo-lines" width="1000" height="700">
          <defs>
            <marker
              id="dot"
              viewBox="0 0 10 10"
              refX="5"
              refY="5"
              markerWidth="5"
              markerHeight="5"
            >
              <circle cx="5" cy="5" r="5" fill="#e87c3e" />
            </marker>
          </defs>
          <line
            x1="411"
            y1="320"
            x2="386"
            y2="352"
            stroke="#e87c3e"
            strokeWidth="15"
            strokeLinecap="butt"
          />
          <line
            x1="589"
            y1="320"
            x2="614"
            y2="352"
            stroke="#e87c3e"
            strokeWidth="15"
            strokeLinecap="butt"
          />
        </svg>

        <div
          className={`monolith balthasar ${getUnitClass("BALTHASAR-2")} ${
            activeUnit === "BALTHASAR-2" ? "active" : ""
          }`}
          onClick={() => openModal("balthasar")}
        >
          <svg viewBox="0 0 255 300" preserveAspectRatio="none">
            <polygon
              points="0,0 255,0 255,240 177.5,300 77.5,300 0,240"
              fill="none"
              stroke="var(--magi-orange)"
              strokeWidth="8"
            />
            <polygon
              points="0,0 255,0 255,240 177.5,300 77.5,300 0,240"
              fill="none"
              stroke="#000"
              strokeWidth="4"
            />
            <polygon
              className="fill-poly"
              points="0,0 255,0 255,240 177.5,300 77.5,300 0,240"
              fill="var(--magi-green)"
            />
          </svg>
          <div className="monolith-content">
            <span className="monolith-label">
              BALTHASAR<span className="monolith-number">・2</span>
            </span>
          </div>
        </div>

        <div
          className={`monolith casper ${getUnitClass("CASPER-3")} ${
            activeUnit === "CASPER-3" ? "active" : ""
          }`}
          onClick={() => openModal("casper")}
        >
          <svg viewBox="0 0 295 215" preserveAspectRatio="none">
            <polygon
              points="0,0 180,0 295,95 295,215 0,215"
              fill="none"
              stroke="var(--magi-orange)"
              strokeWidth="8"
            />
            <polygon
              points="0,0 180,0 295,95 295,215 0,215"
              fill="none"
              stroke="#000"
              strokeWidth="4"
            />
            <polygon
              className="fill-poly"
              points="0,0 180,0 295,95 295,215 0,215"
              fill="var(--magi-green)"
            />
          </svg>
          <div className="monolith-content">
            <span className="monolith-label">
              CASPER<span className="monolith-number">・3</span>
            </span>
          </div>
        </div>

        <div
          className={`monolith melchior ${getUnitClass("MELCHIOR-1")} ${
            activeUnit === "MELCHIOR-1" ? "active" : ""
          }`}
          onClick={() => openModal("melchior")}
        >
          <svg viewBox="0 0 295 215" preserveAspectRatio="none">
            <polygon
              points="115,0 295,0 295,215 0,215 0,95"
              fill="none"
              stroke="var(--magi-orange)"
              strokeWidth="8"
            />
            <polygon
              points="115,0 295,0 295,215 0,215 0,95"
              fill="none"
              stroke="#000"
              strokeWidth="4"
            />
            <polygon
              className="fill-poly"
              points="115,0 295,0 295,215 0,215 0,95"
              fill="var(--magi-green)"
            />
          </svg>
          <div className="monolith-content">
            <span className="monolith-label">
              MELCHIOR<span className="monolith-number">・1</span>
            </span>
          </div>
        </div>

        <div className="magi-center-text">MAGI</div>
      </div>
    </div>
  );
};
