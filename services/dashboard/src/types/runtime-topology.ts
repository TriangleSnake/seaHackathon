export type RuntimeComponentStatus = "running" | "healthy" | "degraded" | "idle";
export type RuntimeThreadStatus = "running" | "waiting" | "completed" | "failed";

export interface RuntimeThread {
  id: string;
  parentId?: string;
  depth: number;
  label: string;
  kind: "request" | "agent" | "tool" | "job";
  status: RuntimeThreadStatus;
  startedAt: string;
  elapsed: string;
  traceId: string;
  requestId: string;
  summary: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  href?: string;
}

export interface RuntimeComponent {
  id: string;
  name: string;
  role: string;
  version: string;
  status: RuntimeComponentStatus;
  latencyMs?: number;
  threads: RuntimeThread[];
}

export interface RuntimeConnection {
  id: string;
  source: string;
  target: string;
  label?: string;
  kind: "runtime" | "control" | "feedback";
}
