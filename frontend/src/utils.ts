import { UnitKey, UnitState, Decision } from "./types";

export const joinPath = (base: string, path: string) => {
  if (!base) return path;
  if (!path) return base;
  const cleanBase = base.replace(/\/+$/, "");
  const cleanPath = path.replace(/^\/+/, "");
  return `${cleanBase}/${cleanPath}`;
};

export const normalizeWsBase = (base: string) => {
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

export const buildWsUrl = (wsUrl: string, wsBaseEnv: string) => {
  if (wsUrl.startsWith("ws://") || wsUrl.startsWith("wss://")) {
    return wsUrl;
  }

  if (wsUrl.startsWith("http://")) {
    return `ws://${wsUrl.slice("http://".length)}`;
  }
  if (wsUrl.startsWith("https://")) {
    return `wss://${wsUrl.slice("https://".length)}`;
  }

  const normalizedBase = normalizeWsBase(wsBaseEnv);
  if (normalizedBase) {
    return `${normalizedBase.replace(/\/+$/, "")}${wsUrl}`;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}${wsUrl}`;
};

export const toDecision = (value: unknown): Decision => {
  if (typeof value !== "string") return "UNKNOWN";
  const normalized = value.trim().toLowerCase();
  if (normalized === "approved" || normalized === "approve") return "APPROVE";
  if (normalized === "denied" || normalized === "deny") return "DENY";
  if (normalized === "conditional") return "CONDITIONAL";
  return "UNKNOWN";
};

export const initialUnitStates: Record<UnitKey, UnitState> = {
  "MELCHIOR-1": "IDLE",
  "BALTHASAR-2": "IDLE",
  "CASPER-3": "IDLE",
};
