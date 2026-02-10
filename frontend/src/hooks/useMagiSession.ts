import { useState, useRef, useCallback, useEffect } from "react";
import {
  UnitKey,
  UnitState,
  Decision,
  LogEntry,
  FinalResult,
  EventPayload,
  HealthResponse,
  AllUnitSettings,
  LogLevel,
  UNIT_KEYS,
} from "../types";
import { joinPath, buildWsUrl, toDecision, initialUnitStates } from "../utils";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const WS_BASE = import.meta.env.VITE_WS_BASE ?? "";

export function useMagiSession() {
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
  const [serverMode, setServerMode] = useState<string>("production");
  const [unitSettings, setUnitSettings] = useState<AllUnitSettings>({
    melchior: { name: "MELCHIOR-1", model: "gpt-4o", temp: 0.2, persona: "科学者としての赤木ナオコ" },
    balthasar: { name: "BALTHASAR-2", model: "gpt-4o", temp: 0.5, persona: "母親としての赤木ナオコ" },
    casper: { name: "CASPER-3", model: "gpt-4o", temp: 0.9, persona: "女としての赤木ナオコ" },
  });

  const logIdRef = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const blinkTimeoutRef = useRef<number | null>(null);
  const requestAbortRef = useRef<AbortController | null>(null);
  const fallbackTimeoutRef = useRef<number | null>(null);
  const cancelledRef = useRef(false);

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
    if (!cancelledRef.current && fallbackTimeoutRef.current !== null) {
      window.clearTimeout(fallbackTimeoutRef.current);
      fallbackTimeoutRef.current = null;
    }
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
      const url = buildWsUrl(wsUrl, WS_BASE);
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
        if (isRunning && !cancelledRef.current) {
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

    if (fallbackTimeoutRef.current !== null) {
      window.clearTimeout(fallbackTimeoutRef.current);
      fallbackTimeoutRef.current = null;
    }

    cancelledRef.current = false;

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
    if (fallbackTimeoutRef.current !== null) {
      window.clearTimeout(fallbackTimeoutRef.current);
      fallbackTimeoutRef.current = null;
    }

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

  const handleCancel = useCallback(async () => {
    if (requestAbortRef.current) {
      requestAbortRef.current.abort();
      requestAbortRef.current = null;
    }

    if (sessionId) {
      cancelledRef.current = true;
      await cancelSession();
      setIsRunning(false);
      setPhase("CANCELLED");
      addLog("SESSION CANCELLED", "error");
      closeWebSocket();

      if (fallbackTimeoutRef.current !== null) {
        window.clearTimeout(fallbackTimeoutRef.current);
      }
      fallbackTimeoutRef.current = window.setTimeout(() => {
        resetSequence();
        fallbackTimeoutRef.current = null;
      }, 5000);
    } else if (isRunning) {
      cancelledRef.current = true;
      setIsRunning(false);
      setPhase("CANCELLED");
      addLog("SESSION INITIALIZATION CANCELLED", "error");
      closeWebSocket();

      if (fallbackTimeoutRef.current !== null) {
        window.clearTimeout(fallbackTimeoutRef.current);
      }
      fallbackTimeoutRef.current = window.setTimeout(() => {
        resetSequence();
        fallbackTimeoutRef.current = null;
      }, 5000);
    }
  }, [sessionId, isRunning, cancelSession, addLog, resetSequence, closeWebSocket]);

  useEffect(() => {
    return () => {
      if (fallbackTimeoutRef.current !== null) {
        window.clearTimeout(fallbackTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch(joinPath(API_BASE, "/api/health"));
        if (res.ok) {
          const data = (await res.json()) as HealthResponse;
          if (data.mode) {
            setServerMode(data.mode);
          }
        }
      } catch (e) {
        // ignore
      }
    };
    checkHealth();
  }, []);

  useEffect(() => () => closeWebSocket(), [closeWebSocket]);

  // Blink effect
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

  return {
    state: {
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
    },
    actions: {
      setPrompt,
      setUnitSettings,
      startSequence,
      handleCancel,
      resetSequence,
      addLog,
    },
  };
}
