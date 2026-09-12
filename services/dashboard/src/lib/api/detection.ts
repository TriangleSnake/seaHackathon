import type { DetectionApiError, DetectionPolicy, DetectionPolicyVersion, DetectionRequest, DetectionResult, DetectionStatus } from "@/types/detection";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/detection/${path}`, { ...init, headers: { "content-type": "application/json", ...init?.headers } });
  const body = await response.json().catch(() => ({})) as T & DetectionApiError;
  if (!response.ok) throw new Error(body.error?.message ?? body.detail ?? `Detection API failed (${response.status})`);
  return body;
}

const post = <T>(path: string, body: unknown) => json<T>(path, { method: "POST", body: JSON.stringify(body) });

export const detectionApi = {
  status: () => json<DetectionStatus>("status"),
  detect: (request: DetectionRequest) => post<DetectionResult>("detect", request),
  listPolicies: () => json<DetectionPolicyVersion[]>("policies/detection"),
  validatePolicy: (policy: DetectionPolicy) => post<{ valid: boolean; version: string }>("policies/detection/validate", policy),
  saveDraft: (policy: DetectionPolicy, source = "human") => post<{ created: boolean; version: string; source: string }>(`policies/detection/drafts?source=${source}`, policy),
  testPolicy: (policy: DetectionPolicy, request: DetectionRequest) => post<DetectionResult>("policies/detection/test", { policy, request }),
  publishPolicy: (policy: DetectionPolicy, source = "human") => post<{ published: boolean; active_version: string }>(`policies/detection/publish?source=${source}`, policy),
  rollbackPolicy: (version: string) => post<{ activated: boolean; active_version: string }>(`policies/detection/rollback/${encodeURIComponent(version)}`, {}),
};
