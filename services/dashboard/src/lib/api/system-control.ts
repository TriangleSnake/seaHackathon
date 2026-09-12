export type TriggerPolicy = {
  policy_id: string;
  version: string;
  enabled: boolean;
  event_type: string;
  source: "messages" | "login_events" | "account_security_events" | "payment_attempts" | "products";
  target_agent: "detection";
  subject_type: string;
  subject_id_field: string;
  requested_checks: Array<"rule_based" | "anomaly" | "llm_classifier" | "ml_classifier">;
  cooldown_seconds: number;
  batch_size: number;
  auto_investigate: boolean;
  updated_at?: string;
};

export type PatrolSchedule = {
  schedule_id: string;
  agent: "patrol";
  enabled: boolean;
  interval_seconds: number;
  config: {
    strategy_weights: { exploit: number; explore: number };
    scope: { subject_types?: string[]; since?: string | null };
  };
  next_run_at?: string | null;
  run_count: number;
  updated_at?: string;
};

export type SystemJob = {
  job_id: string;
  agent: "detection" | "patrol" | "investigation" | "association";
  trigger_type: "event" | "schedule" | "manual";
  trigger_ref: string;
  subject: Record<string, unknown> | null;
  policy_version: string;
  status: "queued" | "running" | "dispatched" | "completed" | "failed" | "dead_letter";
  attempt: number;
  max_attempts: number;
  parent_job_id: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
};

export type SystemCase = {
  case_id: string;
  investigation_job_id: string;
  parent_job_id: string | null;
  subject: Record<string, unknown> | null;
  status: "investigating" | "review" | "failed";
  verdict: "fraud" | "suspicious" | "normal" | "unknown";
  confidence: number | null;
  summary: string | null;
  findings: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  agents_invoked: Array<Record<string, unknown>>;
  scoreboard: Record<string, unknown>;
  stop_reason: string | null;
  detection_result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  updated_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/system/${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? body.error?.message ?? `System API failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const systemControlApi = {
  jobs: () => request<SystemJob[]>("jobs?limit=200"),
  cases: () => request<SystemCase[]>("cases?limit=200"),
  case: (caseId: string) => request<SystemCase>(`cases/${encodeURIComponent(caseId)}`),
  triggers: () => request<TriggerPolicy[]>("control/triggers"),
  schedules: () => request<PatrolSchedule[]>("control/schedules"),
  saveTrigger: (policy: TriggerPolicy) => request<TriggerPolicy>(`control/triggers/${policy.policy_id}`, {
    method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(policy),
  }),
  saveSchedule: (schedule: PatrolSchedule) => request<PatrolSchedule>(`control/schedules/${schedule.schedule_id}`, {
    method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(schedule),
  }),
};
