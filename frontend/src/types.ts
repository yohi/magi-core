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

// ... backend compatibility
export interface PluginConfig {
  id: string;
  enabled: boolean;
  options?: Record<string, unknown>;
}

export interface Attachment {
  id: string;
  type: string;
  content?: string;
  url?: string;
  metadata?: Record<string, unknown>;
}

export type SessionOptionsPayload = {
  model?: string;
  max_rounds?: number;
  api_keys?: Record<string, string>;
  unit_configs?: AllUnitSettings;
  system_config?: SystemSettings;
  plugin?: PluginConfig;
  attachments?: Attachment[];
};

export type HealthResponse = {
  status: string;
  mode?: string;
};

export type UnitSettings = {
  name: string;
  provider: string;
  model: string;
  temp: number;
  persona: string;
  apiKey?: string;
};

export type AllUnitSettings = {
  melchior: UnitSettings;
  balthasar: UnitSettings;
  casper: UnitSettings;
};

export type SystemSettings = {
  debateRounds: number;
  votingThreshold: "majority" | "unanimous";
  providers: Record<string, string>; // provider_id -> api_key
  providerOptions?: Record<string, Record<string, unknown>>; // provider_id -> options
  whitelistProviders: string[];
  persistApiKeys?: boolean; // If true, store keys in localStorage (plaintext)
};

export type ModelDefinition = {
  id: string;
  provider: string;
  name: string;
};

export const UNIT_KEYS: UnitKey[] = ["MELCHIOR-1", "BALTHASAR-2", "CASPER-3"];
