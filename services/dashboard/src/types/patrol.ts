export type PatrolRunStatus = "queued" | "running" | "completed" | "failed";
export type PatrolStrategy = "exploit" | "explore";

export interface PatrolDiscovery {
  id: string;
  subject: string;
  subjectType: string;
  priority: "critical" | "high" | "medium";
  summary: string;
  evidenceRefs: string[];
  caseId?: string;
}

export interface PatrolActivity {
  order: number;
  agent: string;
  action: string;
  tool?: string;
  status: "completed" | "running" | "failed";
  startedAt: string;
  durationMs?: number;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  evidenceRefs: string[];
}

export interface PatrolRun {
  id: string;
  status: PatrolRunStatus;
  strategy: PatrolStrategy;
  scope: string;
  startedAt: string;
  duration: string;
  scannedEntities: number;
  policyRef: { id: string; version: string };
  budget: {
    turns: { used: number; limit: number };
    toolCalls: { used: number; limit: number };
  };
  discoveries: PatrolDiscovery[];
  activity: PatrolActivity[];
}
