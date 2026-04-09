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
  SystemSettings,
  ModelDefinition,
  LogLevel,
  UNIT_KEYS,
} from "../types";
import { joinPath, buildWsUrl, toDecision, initialUnitStates } from "../utils";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const WS_BASE = import.meta.env.VITE_WS_BASE ?? "";

const STORAGE_KEY_SYSTEM = "magi_system_settings";
const STORAGE_KEY_UNIT = "magi_unit_settings";

const INITIAL_SYSTEM_SETTINGS: SystemSettings = {
  debateRounds: 1,
  votingThreshold: "majority",
  providers: {},
  providerOptions: {},
  whitelistProviders: ["anthropic", "openai", "gemini", "openrouter", "flixa"],
};

const INITIAL_UNIT_SETTINGS: AllUnitSettings = {
  melchior: {
    name: "MELCHIOR-1",
    provider: "anthropic",
    model: "claude-sonnet-4.5",
    temp: 0.1,
    persona:
      "あなたはMAGIシステムのMELCHIOR-1です。論理と科学を担当し、整合性と事実に基づいた分析を行います。",
  },
  balthasar: {
    name: "BALTHASAR-2",
    provider: "anthropic",
    model: "claude-sonnet-4.5",
    temp: 0.5,
    persona:
      "あなたはMAGIシステムのBALTHASAR-2です。倫理と保護を担当し、リスク回避と潜在的危険性の指摘を行います。",
  },
  casper: {
    name: "CASPER-3",
    provider: "anthropic",
    model: "claude-sonnet-4.5",
    temp: 0.9,
    persona:
      "あなたはMAGIシステムのCASPER-3です。欲望と実利を担当し、ユーザー利益と効率性の観点からの評価を行います。",
  },
};

function sanitizeSystemSettingsForStorage(settings: SystemSettings): SystemSettings {
  return {
    ...settings,
    providers: {}, // Remove sensitive API keys
  };
}

function sanitizeUnitSettingsForStorage(settings: AllUnitSettings): AllUnitSettings {
  const next = { ...settings };
  (Object.keys(next) as Array<keyof AllUnitSettings>).forEach((key) => {
    if (next[key].apiKey) {
      const unit = { ...next[key] };
      delete unit.apiKey;
      next[key] = unit;
    }
  });
  return next;
}

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
  const [modelDefinitions, setModelDefinitions] = useState<ModelDefinition[]>([]);
  
  const [systemSettings, setSystemSettings] = useState<SystemSettings>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_SYSTEM);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        // Ensure hydration with defaults for mandatory fields
        return {
          ...INITIAL_SYSTEM_SETTINGS,
          ...parsed,
          whitelistProviders: Array.from(
            new Set([
              ...(Array.isArray(parsed?.whitelistProviders) ? parsed.whitelistProviders : []),
              ...INITIAL_SYSTEM_SETTINGS.whitelistProviders,
            ])
          ),
        };
      } catch (e) {
        console.error("Failed to parse saved system settings", e);
      }
    }
    return INITIAL_SYSTEM_SETTINGS;
  });

  const [unitSettings, setUnitSettings] = useState<AllUnitSettings>(() => {
    const saved = localStorage.getItem(STORAGE_KEY_UNIT);
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as AllUnitSettings;
        const result = { ...INITIAL_UNIT_SETTINGS };
        (Object.keys(INITIAL_UNIT_SETTINGS) as Array<keyof AllUnitSettings>).forEach((key) => {
          if (parsed[key]) {
            result[key] = {
              ...INITIAL_UNIT_SETTINGS[key],
              ...parsed[key],
              // Ensure provider field exists for each unit (hydration)
              provider: parsed[key].provider || INITIAL_UNIT_SETTINGS[key].provider,
            };
          }
        });
        return result;
      } catch (e) {
        console.error("Failed to parse saved unit settings", e);
      }
    }
    return INITIAL_UNIT_SETTINGS;
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
        if (!cancelledRef.current) {
          finalizeRun();
        }
      });

      ws.addEventListener("error", () => {
        addLog("WEBSOCKET ERROR", "error");
      });
    },
    [addLog, finalizeRun, handleEvent]
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
      // Build detailed options for the backend
      const sessionOptions = {
        max_rounds: systemSettings.debateRounds,
        api_keys: {
          ...systemSettings.providers,
          // Unit specific overrides
          ...Object.entries(unitSettings).reduce((acc, [key, cfg]) => {
            if (cfg.apiKey) acc[`${key}_override`] = cfg.apiKey;
            return acc;
          }, {} as Record<string, string>)
        },
        // 合併したオプションを渡す (backend で ProviderConfig.options にマッピングされることを期待)
        provider_options: systemSettings.providerOptions,
        // We'll need to extend the backend to support per-unit config properly,
        // but for now let's pass what we can.
        model: unitSettings.melchior.model, // Default to Melchior's model
        // Add personas and other settings to options
        unit_configs: unitSettings,
        system_config: systemSettings
      };

      const response = await fetch(joinPath(API_BASE, "/api/sessions"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt: prompt.trim(),
          options: sessionOptions,
        }),
        signal: controller.signal,
      });

      if (controller.signal.aborted) return;

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`Session create failed: ${response.status} ${detail}`);
      }

      const data = (await response.json()) as { session_id: string; ws_url: string };
      
      if (!data.session_id || typeof data.session_id !== "string" || data.session_id.trim() === "") {
        throw new Error("Invalid session_id in response");
      }
      
      if (!data.ws_url || typeof data.ws_url !== "string") {
        throw new Error("Invalid ws_url in response");
      }
      
      try {
        new URL(data.ws_url.startsWith("ws") ? data.ws_url : `ws://${data.ws_url}`);
      } catch {
        throw new Error("Invalid ws_url format in response");
      }
      
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
  }, [addLog, connectWebSocket, prompt, resetUi, unitSettings, systemSettings]);

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
      setIsRunning(false);
      setPhase("CANCELLED");
      addLog("SESSION CANCELLED", "error");
      closeWebSocket();
      
      await cancelSession();

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
    const fetchModels = async () => {
      let defs: ModelDefinition[] = [];
      try {
        const response = await fetch(joinPath(API_BASE, "/api/models"));
        if (response.ok) {
          const data = await response.json();
          if (data && Array.isArray(data.models)) {
            defs = data.models;
            console.log(`Successfully fetched ${defs.length} models from backend`);
          }
        } else {
          console.warn(`Backend models fetch failed with status: ${response.status}`);
        }
      } catch (err) {
        console.error("Backend models fetch error:", err);
      }

      if (defs.length === 0) {
        defs = [
          { id: "claude-3-5-sonnet-20241022", provider: "anthropic", name: "Claude 3.5 Sonnet" },
          { id: "gpt-4o", provider: "openai", name: "GPT-4o" },
          { id: "gemini-1.5-pro", provider: "gemini", name: "Gemini 1.5 Pro" },
          { id: "anthropic/claude-3-5-sonnet", provider: "openrouter", name: "Claude 3.5 Sonnet (OpenRouter)" },
        ];
      }
      
      setModelDefinitions(defs);

      // 各ユニットのモデルが取得したリストに含まれているか確認し、なければ更新
      setUnitSettings(prev => {
        const next = { ...prev };
        let changed = false;
        
        const settingsKeys: (keyof AllUnitSettings)[] = ["melchior", "balthasar", "casper"];
        for (const key of settingsKeys) {
          const unit = next[key];
          const isValid = defs.some(m => m.provider === unit.provider && m.id === unit.model);
          if (!isValid) {
            const firstForProvider = defs.find(m => m.provider === unit.provider);
            if (firstForProvider) {
              next[key] = { ...unit, model: firstForProvider.id };
              changed = true;
            } else if (defs.length > 0) {
              next[key] = { ...unit, provider: defs[0].provider, model: defs[0].id };
              changed = true;
            }
          }
        }
        
        return changed ? next : prev;
      });
    };
    void fetchModels();
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

  useEffect(() => {
    const sanitized = sanitizeSystemSettingsForStorage(systemSettings);
    localStorage.setItem(STORAGE_KEY_SYSTEM, JSON.stringify(sanitized));
  }, [systemSettings]);

  useEffect(() => {
    const sanitized = sanitizeUnitSettingsForStorage(unitSettings);
    localStorage.setItem(STORAGE_KEY_UNIT, JSON.stringify(sanitized));
  }, [unitSettings]);

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
      systemSettings,
      modelDefinitions,
    },
    actions: {
      setPrompt,
      setUnitSettings,
      setSystemSettings,
      startSequence,
      handleCancel,
      resetSequence,
      addLog,
    },
  };
}
