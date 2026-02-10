export type LogLevel = "normal" | "info" | "error";
export type UnitKey = "MELCHIOR-1" | "BALTHASAR-2" | "CASPER-3";
export type UnitState = "IDLE" | "THINKING" | "DEBATING" | "VOTING" | "VOTED";
export type Decision = "APPROVE" | "DENY" | "CONDITIONAL" | "UNKNOWN";

export type LogEntry = {
  id: number;
  message: string;
  level: LogLevel;
};

export type FinalResult = {
  decision: Decision;
  votes: Record<string, { vote?: string; reason?: string }>;
  summary?: string;
};

export type EventPayload = {
  type?: string;
  [key: string]: unknown;
};

export type HealthResponse = {
  status: string;
  mode?: string;
};

export type UnitSettings = {
  name: string;
  model: string;
  temp: number;
  persona: string;
};

export type AllUnitSettings = {
  melchior: UnitSettings;
  balthasar: UnitSettings;
  casper: UnitSettings;
};

export const UNIT_KEYS: UnitKey[] = ["MELCHIOR-1", "BALTHASAR-2", "CASPER-3"];
