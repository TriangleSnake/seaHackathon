import type { ScoreboardConfig } from "@/types/scoreboard";

const configs: ScoreboardConfig[] = [
  {
    id: "scb_003", version: 3, status: "active", scoringPolicyVersion: "v5",
    fraudThreshold: 0.82, normalThreshold: 0.24,
    budgets: { maxAgentCalls: 5, maxToolCalls: 20, maxSteps: 8, maxTokens: 30000, maxCostUsd: 1.5 },
    stoppingRules: { directEvidence: true, falsePositiveEvidence: true, diminishingReturns: true },
    agents: [
      { name: "chat_agent", enabled: true, priority: 1, costWeight: 1 },
      { name: "order_agent", enabled: true, priority: 2, costWeight: 1.2 },
      { name: "shop_agent", enabled: true, priority: 3, costWeight: 1.4 }
    ],
    createdAt: "2026-09-11T08:42:00Z", createdBy: "Lin Yu-ting", note: "提高直接證據的提前停止權重，控制深度調查成本。"
  },
  {
    id: "scb_002", version: 2, status: "retired", scoringPolicyVersion: "v4",
    fraudThreshold: 0.85, normalThreshold: 0.2,
    budgets: { maxAgentCalls: 4, maxToolCalls: 16, maxSteps: 7, maxTokens: 24000, maxCostUsd: 1.2 },
    stoppingRules: { directEvidence: true, falsePositiveEvidence: false, diminishingReturns: true },
    agents: [
      { name: "chat_agent", enabled: true, priority: 1, costWeight: 1 },
      { name: "order_agent", enabled: true, priority: 2, costWeight: 1.2 },
      { name: "shop_agent", enabled: false, priority: 3, costWeight: 1.4 }
    ],
    createdAt: "2026-08-28T03:10:00Z", createdBy: "System", note: "初始生產基準。"
  },
  {
    id: "scb_001", version: 1, status: "retired", scoringPolicyVersion: "v3",
    fraudThreshold: 0.88, normalThreshold: 0.18,
    budgets: { maxAgentCalls: 3, maxToolCalls: 12, maxSteps: 6, maxTokens: 18000, maxCostUsd: 0.9 },
    stoppingRules: { directEvidence: true, falsePositiveEvidence: false, diminishingReturns: false },
    agents: [
      { name: "chat_agent", enabled: true, priority: 1, costWeight: 1 },
      { name: "order_agent", enabled: true, priority: 2, costWeight: 1.1 },
      { name: "shop_agent", enabled: false, priority: 3, costWeight: 1.3 }
    ],
    createdAt: "2026-08-12T06:20:00Z", createdBy: "System", note: "沙盒驗證設定。"
  }
];

const wait = (ms = 240) => new Promise((resolve) => setTimeout(resolve, ms));

export const scoreboardApi = {
  async list(): Promise<ScoreboardConfig[]> { await wait(); return structuredClone(configs); },
  async create(input: ScoreboardConfig): Promise<ScoreboardConfig> { await wait(500); return { ...input, id: `scb_${String(input.version).padStart(3, "0")}`, status: "draft" }; }
};
