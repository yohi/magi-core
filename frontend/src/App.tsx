import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type LogLevel = "normal" | "info" | "error";
type UnitKey = "MELCHIOR-1" | "BALTHASAR-2" | "CASPER-3";
type UnitState = "IDLE" | "THINKING" | "DEBATING" | "VOTING" | "VOTED";
type Decision = "APPROVE" | "DENY" | "CONDITIONAL" | "UNKNOWN";

type LogEntry = {
  id: number;
  message: string;
  level: LogLevel;
};

type FinalResult = {
  decision: Decision;
  votes: Record<string, { vote?: string; reason?: string }>;
  summary?: string;
};

type EventPayload = {
  type?: string;
  [key: string]: unknown;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const WS_BASE = import.meta.env.VITE_WS_BASE ?? "";

const UNIT_KEYS: UnitKey[] = ["MELCHIOR-1", "BALTHASAR-2", "CASPER-3"];

const initialUnitStates: Record<UnitKey, UnitState> = {
  "MELCHIOR-1": "IDLE",
  "BALTHASAR-2": "IDLE",
  "CASPER-3": "IDLE",
};


const joinPath = (base: string, path: string) => {
  if (!base) return path;
  return `${base.replace(/\/+$/, "")}${path}`;
};

const normalizeWsBase = (base: string) => {
  if (!base) return "";
  if (base.startsWith("ws://") || base.startsWith("wss://")) {
    return base;
  }
  if (base.startsWith("http://")) {
    return `ws://${base.slice("http://".length)}`;
  }
  if (base.startsWith("https://")) {
    return `wss://${base.slice("https://".length)}`;
  }
  return base;
};

const buildWsUrl = (wsUrl: string) => {
  if (wsUrl.startsWith("ws://") || wsUrl.startsWith("wss://")) {
    return wsUrl;
  }

  const normalizedBase = normalizeWsBase(WS_BASE);
  if (normalizedBase) {
    return `${normalizedBase.replace(/\/+$/, "")}${wsUrl}`;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}${wsUrl}`;
};

const toDecision = (value: unknown): Decision => {
  if (typeof value !== "string") return "UNKNOWN";
  const normalized = value.trim().toLowerCase();
  if (normalized === "approved" || normalized === "approve") return "APPROVE";
  if (normalized === "denied" || normalized === "deny") return "DENY";
  if (normalized === "conditional") return "CONDITIONAL";
  return "UNKNOWN";
};

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [phase, setPhase] = useState("IDLE");
  const [progress, setProgress] = useState(0);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [finalResult, setFinalResult] = useState<FinalResult | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [unitStates, setUnitStates] = useState(initialUnitStates);
  const [activeUnit, setActiveUnit] = useState<UnitKey | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentEditingUnit, setCurrentEditingUnit] = useState<
    "melchior" | "balthasar" | "casper" | null
  >(null);
  const [unitSettings, setUnitSettings] = useState({
    melchior: {
      name: "MELCHIOR-1",
      model: "gpt-4o",
      temp: 0.2,
      persona: "科学者としての赤木ナオコ",
    },
    balthasar: {
      name: "BALTHASAR-2",
      model: "gpt-4o",
      temp: 0.5,
      persona: "母親としての赤木ナオコ",
    },
    casper: {
      name: "CASPER-3",
      model: "gpt-4o",
      temp: 0.9,
      persona: "女としての赤木ナオコ",
    },
  });

  const logIdRef = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const scalerRef = useRef<HTMLDivElement | null>(null);
  const blinkTimeoutRef = useRef<number | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const requestAbortRef = useRef<AbortController | null>(null);

  const addLog = useCallback((message: string, level: LogLevel = "normal") => {
    logIdRef.current += 1;
    const time = new Date().toISOString().split("T")[1].slice(0, 8);
    const entry: LogEntry = {
      id: logIdRef.current,
      message: `[${time}] ${message}`,
      level,
    };
    setLogs((prev) => {
      const next = [...prev, entry];
      if (next.length > 200) {
        return next.slice(-200);
      }
      return next;
    });
  }, []);

  const resetUi = useCallback(() => {
    setPhase("IDLE");
    setProgress(0);
    setDecision(null);
    setFinalResult(null);
    setLogs([]);
    setUnitStates(initialUnitStates);
    setActiveUnit(null);
  }, []);

  const closeWebSocket = useCallback(() => {
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        // noop
      }
    }
    wsRef.current = null;
  }, []);

  const finalizeRun = useCallback(() => {
    setIsRunning(false);
    closeWebSocket();
  }, [closeWebSocket]);

  const handleEvent = useCallback(
    (payload: EventPayload) => {
      const evtType = typeof payload.type === "string" ? payload.type : "";

      if (evtType === "phase") {
        const nextPhase = typeof payload.phase === "string" ? payload.phase : "UNKNOWN";
        setPhase(nextPhase);
      }

      if (evtType === "progress") {
        const pct = Number(payload.pct ?? 0);
        const value = Number.isNaN(pct) ? 0 : Math.max(0, Math.min(100, pct));
        setProgress(value);
      }

      if (evtType === "log") {
        const level = typeof payload.level === "string" ? payload.level.toUpperCase() : "";
        const logLevel: LogLevel =
          level === "ERROR" ? "error" : level === "INFO" ? "info" : "normal";
        const lines = Array.isArray(payload.lines) ? payload.lines : [payload.lines];
        for (const line of lines) {
          if (typeof line === "string" && line.trim()) {
            addLog(line, logLevel);
          }
        }
      }

      if (evtType === "unit") {
        const unit = typeof payload.unit === "string" ? payload.unit : "";
        if (UNIT_KEYS.includes(unit as UnitKey)) {
          const unitKey = unit as UnitKey;
          const stateValue = typeof payload.state === "string" ? payload.state : "IDLE";
          const message = typeof payload.message === "string" ? payload.message : "";
          const score =
            typeof payload.score === "number" && !Number.isNaN(payload.score)
              ? payload.score
              : null;

          setUnitStates((prev) => ({
            ...prev,
            [unitKey]: stateValue as UnitState,
          }));

          if (message) {
            const scoreText = score !== null ? ` (score ${score.toFixed(2)})` : "";
            addLog(`${unitKey}: ${message}${scoreText}`, "info");
          }

          setActiveUnit(unitKey);
        }
      }

      if (evtType === "final") {
        const nextDecision = toDecision(payload.decision);
        const votes =
          typeof payload.votes === "object" && payload.votes ? payload.votes : {};
        const summary = typeof payload.summary === "string" ? payload.summary : undefined;
        setDecision(nextDecision);
        setFinalResult({ decision: nextDecision, votes: votes as FinalResult["votes"], summary });
        setPhase("RESOLVED");
        setProgress(100);
        addLog(`DECISION: ${nextDecision}`, nextDecision === "DENY" ? "error" : "info");
        finalizeRun();
      }

      if (evtType === "error") {
        const message = typeof payload.message === "string" ? payload.message : "Unknown error";
        addLog(`ERROR: ${message}`, "error");
        setPhase("ERROR");
        finalizeRun();
      }
    },
    [addLog, finalizeRun]
  );

  const connectWebSocket = useCallback(
    (wsUrl: string) => {
      const url = buildWsUrl(wsUrl);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.addEventListener("open", () => {
        addLog("WEBSOCKET CONNECTED", "info");
      });

      ws.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data) as EventPayload;
          handleEvent(payload);
        } catch (err) {
          const message = err instanceof Error ? err.message : "Invalid payload";
          addLog(`ERROR: ${message}`, "error");
        }
      });

      ws.addEventListener("close", () => {
        addLog("WEBSOCKET CLOSED", "info");
        if (isRunning) {
          finalizeRun();
        }
      });

      ws.addEventListener("error", () => {
        addLog("WEBSOCKET ERROR", "error");
      });
    },
    [addLog, finalizeRun, handleEvent, isRunning]
  );

  const startSequence = useCallback(async () => {
    if (!prompt.trim()) {
      addLog("ERROR: NO PROMPT DATA", "error");
      return;
    }

    if (requestAbortRef.current) {
      requestAbortRef.current.abort();
    }
    const controller = new AbortController();
    requestAbortRef.current = controller;

    resetUi();
    setIsRunning(true);
    setSessionId(null);

    addLog("INITIALIZING MAGI SYSTEM...");

    try {
      const response = await fetch(joinPath(API_BASE, "/api/sessions"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt: prompt.trim(),
          options: {
            max_rounds: 1,
            model:
              unitSettings.melchior.model ||
              unitSettings.balthasar.model ||
              unitSettings.casper.model ||
              undefined,
          },
        }),
        signal: controller.signal,
      });

      if (controller.signal.aborted) return;

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`Session create failed: ${response.status} ${detail}`);
      }

      const data = (await response.json()) as { session_id: string; ws_url: string };
      
      if (controller.signal.aborted) return;

      setSessionId(data.session_id);
      addLog(`SESSION CREATED: ${data.session_id}`, "info");
      connectWebSocket(data.ws_url);
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return;
      }
      const message = err instanceof Error ? err.message : "Unknown error";
      addLog(`ERROR: ${message}`, "error");
      setIsRunning(false);
    } finally {
      if (requestAbortRef.current === controller) {
        requestAbortRef.current = null;
      }
    }
  }, [addLog, connectWebSocket, prompt, resetUi, unitSettings]);

  const cancelSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      await fetch(joinPath(API_BASE, `/api/sessions/${sessionId}/cancel`), {
        method: "POST",
      });
    } catch {
      // ignore
    }
  }, [sessionId]);

  const resetSequence = useCallback(async () => {
    if (requestAbortRef.current) {
      requestAbortRef.current.abort();
      requestAbortRef.current = null;
    }

    if (isRunning || sessionId) {
      await cancelSession();
    }
    closeWebSocket();
    setSessionId(null);
    setIsRunning(false);
    resetUi();
    addLog("SYSTEM RESET COMPLETE.");
  }, [addLog, cancelSession, closeWebSocket, isRunning, sessionId, resetUi]);

  const openModal = (unitKey: "melchior" | "balthasar" | "casper") => {
    setCurrentEditingUnit(unitKey);
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setCurrentEditingUnit(null);
  };

  const saveSettings = () => {
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
  };

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

  useEffect(() => () => closeWebSocket(), [closeWebSocket]);

  useEffect(() => {
    if (!logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if (!activeUnit) return;
    if (blinkTimeoutRef.current !== null) {
      window.clearTimeout(blinkTimeoutRef.current);
    }
    blinkTimeoutRef.current = window.setTimeout(() => {
      setActiveUnit(null);
      blinkTimeoutRef.current = null;
    }, 220);
    return () => {
      if (blinkTimeoutRef.current !== null) {
        window.clearTimeout(blinkTimeoutRef.current);
        blinkTimeoutRef.current = null;
      }
    };
  }, [activeUnit]);

  const resultRows = useMemo(() => {
    if (!finalResult) return [];
    return UNIT_KEYS.map((unit) => {
      const vote = finalResult.votes[unit] || {};
      return {
        unit,
        vote: vote.vote ?? "N/A",
        reason: vote.reason ?? "",
      };
    });
  }, [finalResult]);

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
  const phaseColor =
    decision === "APPROVE"
      ? "var(--magi-blue)"
      : decision === "DENY" || phase === "ERROR" || phase === "CANCELLED"
        ? "var(--magi-red)"
        : "var(--magi-orange)";

  return (
    <div className="app-root">
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
              <marker id="dot" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5">
                <circle cx="5" cy="5" r="5" fill="#e87c3e" />
              </marker>
            </defs>
            <line x1="411" y1="320" x2="386" y2="352" stroke="#e87c3e" strokeWidth="15" strokeLinecap="butt" />
            <line x1="589" y1="320" x2="614" y2="352" stroke="#e87c3e" strokeWidth="15" strokeLinecap="butt" />
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
              <polygon points="0,0 180,0 295,95 295,215 0,215" fill="none" stroke="var(--magi-orange)" strokeWidth="8" />
              <polygon points="0,0 180,0 295,95 295,215 0,215" fill="none" stroke="#000" strokeWidth="4" />
              <polygon className="fill-poly" points="0,0 180,0 295,95 295,215 0,215" fill="var(--magi-green)" />
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
              <polygon points="115,0 295,0 295,215 0,215 0,95" fill="none" stroke="var(--magi-orange)" strokeWidth="8" />
              <polygon points="115,0 295,0 295,215 0,215 0,95" fill="none" stroke="#000" strokeWidth="4" />
              <polygon className="fill-poly" points="115,0 295,0 295,215 0,215 0,95" fill="var(--magi-green)" />
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

      <div className="dashboard-ui">
        <div className="status-bar">
          <div className="phase-indicator" style={{ color: phaseColor }}>
            PHASE: <span id="phase-txt">{phase}</span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${progress}%` }}></div>
          </div>
        </div>

        <div className="panel log-panel" id="log-container" ref={logRef}>
          {logs.map((log) => (
            <div key={log.id} className={`log-entry ${log.level}`}>
              {log.message}
            </div>
          ))}
        </div>

        <div className="panel result-console" id="result-console" style={{ display: finalResult ? "flex" : "none" }}>
          <div className="result-header">FINAL DECISION</div>
          <div className="result-content" id="result-content">
            {finalResult &&
              resultRows.map((row) => (
                <div className="vote-row" key={row.unit}>
                  <span>{row.unit}:</span>
                  <span className={row.vote === "YES" ? "vote-yes" : row.vote === "NO" ? "vote-no" : ""}>
                    {row.vote}
                  </span>
                  {row.reason && <span className="vote-reason"> {row.reason}</span>}
                </div>
              ))}
            {finalResult?.summary && <div className="summary">{finalResult.summary}</div>}
          </div>
        </div>

        <div className="panel control-panel">
          <textarea
            id="prompt-input"
            placeholder="ENTER PROMPT DATA..."
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            disabled={isRunning}
          ></textarea>
          <div className="btn-group">
            <button id="btn-start" onClick={startSequence} disabled={isRunning}>
              START
            </button>
            <button id="btn-reset" onClick={resetSequence} disabled={!sessionId && !isRunning}>
              RESET
            </button>
          </div>
        </div>
      </div>

      {isModalOpen && currentEditingUnit && (
        <div id="settings-modal" className="settings-modal" style={{ display: "flex" }}>
          <div className="modal-content">
            <h2 id="modal-title">UNIT: {unitSettings[currentEditingUnit].name}</h2>
            <div className="form-group">
              <label>MODEL:</label>
              <input
                type="text"
                value={unitSettings[currentEditingUnit].model}
                onChange={(event) =>
                  setUnitSettings((prev) => ({
                    ...prev,
                    [currentEditingUnit]: {
                      ...prev[currentEditingUnit],
                      model: event.target.value,
                    },
                  }))
                }
              />
            </div>
            <div className="form-group">
              <label>TEMPERATURE:</label>
              <input
                type="number"
                step="0.1"
                min={0}
                max={1}
                value={unitSettings[currentEditingUnit].temp}
                onChange={(event) =>
                  setUnitSettings((prev) => ({
                    ...prev,
                    [currentEditingUnit]: {
                      ...prev[currentEditingUnit],
                      temp: Number(event.target.value),
                    },
                  }))
                }
              />
            </div>
            <div className="form-group">
              <label>PERSONA:</label>
              <textarea
                value={unitSettings[currentEditingUnit].persona}
                onChange={(event) =>
                  setUnitSettings((prev) => ({
                    ...prev,
                    [currentEditingUnit]: {
                      ...prev[currentEditingUnit],
                      persona: event.target.value,
                    },
                  }))
                }
              ></textarea>
            </div>
            <div className="modal-buttons">
              <button id="btn-save" onClick={saveSettings}>
                SAVE
              </button>
              <button id="btn-cancel" onClick={closeModal}>
                CANCEL
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
