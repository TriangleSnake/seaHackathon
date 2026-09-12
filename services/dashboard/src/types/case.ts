export type CaseVerdict = "fraud" | "suspicious" | "normal" | "unknown";
export type CaseStatus = "investigating" | "review" | "fraud" | "normal";

export interface FraudCase {
  id: string;
  subject: string;
  subjectType: "account" | "shop";
  status: CaseStatus;
  verdict: CaseVerdict;
  fraudScore?: number;
  confidence?: number;
  triggers: string[];
  updatedAt: string;
  summary: string;
  evidenceCount: number;
  invokedAgents: string[];
}

export interface CaseEvidence {
  id: string;
  source: string;
  type: "message" | "login_ip" | "url_reputation" | "transaction" | "device";
  observedAt: string;
  summary: string;
  collectedBy: string;
  raw: Record<string, unknown>;
}

export interface AgentInvocation {
  order: number;
  component: string;
  status: "completed" | "submitted" | "running" | "pending";
  reason: string;
  inputRefs: string[];
  output: string;
  evidenceRefs: string[];
  durationMs: number;
  agentRef?: {
    parent: string;
    slug: string;
    version: string;
  };
}

export interface CaseInvestigation {
  detectionId: string;
  investigationId: string;
  stopReason: string;
  evidence: CaseEvidence[];
  invocations: AgentInvocation[];
}
