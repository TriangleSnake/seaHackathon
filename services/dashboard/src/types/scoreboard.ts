export type AgentName = "chat_agent" | "order_agent" | "shop_agent";

export interface AgentConfig {
  name: AgentName;
  enabled: boolean;
  priority: number;
  costWeight: number;
}

export interface ScoreboardConfig {
  id: string;
  version: number;
  status: "active" | "draft" | "retired";
  scoringPolicyVersion: string;
  fraudThreshold: number;
  normalThreshold: number;
  budgets: {
    maxAgentCalls: number;
    maxToolCalls: number;
    maxSteps: number;
    maxTokens: number;
    maxCostUsd: number;
  };
  stoppingRules: {
    directEvidence: boolean;
    falsePositiveEvidence: boolean;
    diminishingReturns: boolean;
  };
  agents: AgentConfig[];
  createdAt: string;
  createdBy: string;
  note: string;
}
