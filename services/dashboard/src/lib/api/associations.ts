import type { AssociationGraphResponse } from "@/types/association";

// Mock API payload. The UI treats entity types, discovery strategies and
// evidence sources as opaque values supplied by Association Agent.
export const associationGraph: AssociationGraphResponse = {
  focusEntityId: "entity:acct_8f3a19",
  strategy: "focused",
  policyRef: { id: "association-focused", version: "0.1.0" },
  entities: [
    { id: "entity:acct_8f3a19", label: "acct_8f3a19", entityType: "帳號", riskScore: 0.91, firstObserved: "2026-09-08 14:22", caseIds: ["CASE-2026-0912-0841"], evidenceRefs: ["EV-0841-03", "EV-0841-05"] },
    { id: "entity:acct_91de22", label: "acct_91de22", entityType: "帳號", riskScore: 0.86, firstObserved: "2026-09-09 07:13", caseIds: ["CASE-2026-0912-0841", "CASE-2026-0912-0828"], evidenceRefs: ["EV-0841-06"] },
    { id: "entity:shop_northstar", label: "shop_northstar", entityType: "商店", riskScore: 0.73, firstObserved: "2026-09-10 12:06", caseIds: ["CASE-2026-0912-0828"], evidenceRefs: ["EV-0828-04"] },
    { id: "entity:acct_72de90", label: "acct_72de90", entityType: "帳號", riskScore: 0.58, firstObserved: "2026-09-12 09:51", caseIds: ["CASE-2026-0912-0794"], evidenceRefs: ["EV-0794-02"] },
    { id: "entity:cluster_a17", label: "關聯群組 A-17", entityType: "衍生實體", riskScore: 0.69, firstObserved: "2026-09-11 18:40", caseIds: ["CASE-2026-0912-0841", "CASE-2026-0912-0817"], evidenceRefs: ["EV-0841-04", "EV-0817-03"] },
    { id: "entity:pattern_p42", label: "行為樣式 P-42", entityType: "衍生實體", riskScore: 0.41, firstObserved: "2026-09-12 08:24", caseIds: ["CASE-2026-0912-0766"], evidenceRefs: ["EV-0766-02"] },
  ],
  relations: [
    { id: "rel:001", source: "entity:acct_8f3a19", target: "entity:acct_91de22", confidence: 0.93, caseIds: ["CASE-2026-0912-0841"], evidenceRefs: ["EV-0841-06"] },
    { id: "rel:002", source: "entity:acct_8f3a19", target: "entity:shop_northstar", confidence: 0.84, caseIds: ["CASE-2026-0912-0841", "CASE-2026-0912-0828"], evidenceRefs: ["EV-0841-05"] },
    { id: "rel:003", source: "entity:acct_8f3a19", target: "entity:cluster_a17", confidence: 0.89, caseIds: ["CASE-2026-0912-0841", "CASE-2026-0912-0817"], evidenceRefs: ["EV-0841-03", "EV-0841-04"] },
    { id: "rel:004", source: "entity:cluster_a17", target: "entity:acct_72de90", confidence: 0.76, caseIds: ["CASE-2026-0912-0794"], evidenceRefs: ["EV-0794-02"] },
    { id: "rel:005", source: "entity:shop_northstar", target: "entity:pattern_p42", confidence: 0.68, caseIds: ["CASE-2026-0912-0766"], evidenceRefs: ["EV-0766-02"] },
  ],
};

export const associationsApi = {
  async getGraph(): Promise<AssociationGraphResponse> {
    return structuredClone(associationGraph);
  },
  async listLiveJobs(): Promise<AssociationJobState[]> { return liveJson<AssociationJobState[]>("association/jobs?limit=50"); },
  async getLiveJob(id: string): Promise<AssociationJobState> { return liveJson<AssociationJobState>(`association/jobs/${encodeURIComponent(id)}`); },
};

async function liveJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api/association/${path}`, { cache: "no-store" });
  const body = await response.json().catch(() => ({})) as T & { detail?: string; error?: { message?: string } };
  if (!response.ok) throw new Error(body.error?.message ?? body.detail ?? `Association API failed (${response.status})`);
  return body;
}

export interface AssociationJobState {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  case_id: string;
  strategy: "focused" | "discovery";
  policy_ref: { id: string; version: string };
  created_at: string;
  updated_at: string;
  result: null | {
    case_id: string;
    strategy: "focused" | "discovery";
    policy_ref: { id: string; version: string };
    nodes: Array<{ id: string; type: string; label?: string | null; attributes: Record<string, unknown> }>;
    edges: Array<{ source: string; target: string; type: string; relationship: "observed" | "inferred"; value?: string | null; confidence: number; occurrence_count?: number | null; first_seen_at?: string | null; last_seen_at?: string | null; evidence_refs: string[] }>;
    related_subjects: Array<{ subject: { type: string; id: string }; association_score: number; reason: string; relation_paths: Array<{ nodes: string[]; edge_types: string[]; evidence_refs: string[] }>; evidence_refs: string[] }>;
    evidence: Array<{ id: string; source: string; type: string; ref_id?: string | null; observed_at?: string | null; data: Record<string, unknown> }>;
  };
  error: string | null;
  callback_status: "not_configured" | "pending" | "delivered" | "failed";
  callback_attempts: number;
  callback_error: string | null;
}
