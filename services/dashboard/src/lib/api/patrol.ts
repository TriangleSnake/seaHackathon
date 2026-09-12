import type { PatrolDiscovery, PatrolRun, PatrolRunStatus, PatrolStrategy } from "@/types/patrol";

const discoveryPool: PatrolDiscovery[] = [
  { id: "DISC-0912-221", subject: "acct_54ba20", subjectType: "帳號", priority: "critical", summary: "多個對話出現相同站外付款導向，且與既有案件證據重疊。", evidenceRefs: ["EV-P221-01", "EV-P221-02", "EV-P221-03", "EV-P221-04"], caseId: "CASE-2026-0912-0859" },
  { id: "DISC-0912-220", subject: "shop_lumen_tw", subjectType: "商店", priority: "high", summary: "退款行為與多個關聯實體的活動時間高度重疊。", evidenceRefs: ["EV-P220-01", "EV-P220-02", "EV-P220-03"], caseId: "CASE-2026-0912-0851" },
  { id: "DISC-0912-219", subject: "acct_118caa", subjectType: "帳號", priority: "medium", summary: "新帳號在短時間內產生異常密集的高價刊登活動。", evidenceRefs: ["EV-P219-01", "EV-P219-02", "EV-P219-03"] },
  { id: "DISC-0912-218", subject: "acct_99d270", subjectType: "帳號", priority: "high", summary: "活動軌跡與一組已確認的高風險實體形成新的關聯。", evidenceRefs: ["EV-P218-01", "EV-P218-02"], caseId: "CASE-2026-0912-0848" },
];

function makeRun(input: { id: string; status: PatrolRunStatus; strategy: PatrolStrategy; scope: string; startedAt: string; duration: string; scannedEntities: number; discoveryCount: number; turns: number; toolCalls: number }): PatrolRun {
  const limit = input.strategy === "exploit" ? 12 : 16;
  const discoveries = Array.from({ length: Math.min(input.discoveryCount, discoveryPool.length) }, (_, index) => ({ ...discoveryPool[index], id: `${discoveryPool[index].id}-${input.id.slice(-3)}` }));
  const running = input.status === "running";
  return {
    ...input,
    policyRef: { id: `patrol-${input.strategy}`, version: "0.1.0" },
    budget: { turns: { used: input.turns, limit }, toolCalls: { used: input.toolCalls, limit: input.strategy === "exploit" ? 24 : 32 } },
    discoveries,
    activity: [
      { order: 1, agent: "Patrol Agent", action: "載入本次 Policy 與巡查範圍", status: "completed", startedAt: input.startedAt, durationMs: 42, input: { strategy: input.strategy, scope: input.scope, policy_version: "0.1.0" }, output: { allowed: true, max_turns: limit }, evidenceRefs: [] },
      { order: 2, agent: "Patrol Agent", action: "取得近期活動概況", tool: "get_patrol_overview", status: "completed", startedAt: input.startedAt, durationMs: 184, input: { window: "6h", scope: input.scope }, output: { scanned_entities: input.scannedEntities, candidate_segments: 6 }, evidenceRefs: [] },
      { order: 3, agent: "Patrol Agent", action: input.strategy === "explore" ? "抽樣並檢查候選實體" : "沿核准模式搜尋候選實體", tool: input.strategy === "explore" ? "sample_accounts" : "search_accounts", status: "completed", startedAt: input.startedAt, durationMs: 692, input: { batch_size: 200, cursor: "segment:04" }, output: { candidates: Math.max(12, input.discoveryCount * 5) }, evidenceRefs: discoveries.flatMap((item) => item.evidenceRefs.slice(0, 1)) },
      { order: 4, agent: "Patrol Agent", action: running ? "驗證發現與補齊證據" : "完成證據驗證並提交 Investigation", tool: "get_evidence_records", status: running ? "running" : input.status === "failed" ? "failed" : "completed", startedAt: input.startedAt, durationMs: running ? undefined : 518, input: { discovery_ids: discoveries.map((item) => item.id) }, output: running ? { validated: Math.max(1, discoveries.length - 1), pending: 1 } : input.status === "failed" ? { error: "upstream_timeout", retryable: true } : { submitted: discoveries.filter((item) => item.caseId).length }, evidenceRefs: discoveries.flatMap((item) => item.evidenceRefs) },
    ],
  };
}

export const patrolRuns: PatrolRun[] = [
  makeRun({ id: "PTR-0912-031", status: "completed", strategy: "exploit", scope: "高風險賣家與新註冊帳號", startedAt: "2026-09-12 10:00", duration: "06:42", scannedEntities: 3240, discoveryCount: 4, turns: 9, toolCalls: 18 }),
  makeRun({ id: "PTR-0912-030", status: "completed", strategy: "explore", scope: "站外付款行為樣本", startedAt: "2026-09-12 09:22", duration: "12:18", scannedEntities: 4810, discoveryCount: 3, turns: 14, toolCalls: 27 }),
  makeRun({ id: "PTR-0912-029", status: "running", strategy: "explore", scope: "全站增量巡查", startedAt: "2026-09-12 08:00", duration: "執行中", scannedEntities: 6370, discoveryCount: 3, turns: 8, toolCalls: 16 }),
  makeRun({ id: "PTR-0912-028", status: "completed", strategy: "exploit", scope: "高退款率商店", startedAt: "2026-09-12 06:00", duration: "08:51", scannedEntities: 2870, discoveryCount: 2, turns: 10, toolCalls: 19 }),
  makeRun({ id: "PTR-0912-027", status: "completed", strategy: "exploit", scope: "近期核准模式回溯", startedAt: "2026-09-12 04:00", duration: "07:14", scannedEntities: 2214, discoveryCount: 1, turns: 7, toolCalls: 13 }),
  makeRun({ id: "PTR-0912-026", status: "failed", strategy: "explore", scope: "新註冊帳號活動樣本", startedAt: "2026-09-12 02:00", duration: "03:09", scannedEntities: 918, discoveryCount: 1, turns: 4, toolCalls: 8 }),
  makeRun({ id: "PTR-0911-025", status: "completed", strategy: "exploit", scope: "重複訊息模式", startedAt: "2026-09-11 22:00", duration: "09:37", scannedEntities: 3560, discoveryCount: 3, turns: 11, toolCalls: 22 }),
  makeRun({ id: "PTR-0911-024", status: "completed", strategy: "explore", scope: "晚間交易活動樣本", startedAt: "2026-09-11 20:00", duration: "11:02", scannedEntities: 5124, discoveryCount: 2, turns: 13, toolCalls: 25 }),
  makeRun({ id: "PTR-0911-023", status: "completed", strategy: "exploit", scope: "高風險商店活動", startedAt: "2026-09-11 18:00", duration: "06:58", scannedEntities: 2642, discoveryCount: 2, turns: 8, toolCalls: 15 }),
  makeRun({ id: "PTR-0911-022", status: "completed", strategy: "explore", scope: "商品刊登異常樣本", startedAt: "2026-09-11 16:00", duration: "10:45", scannedEntities: 4780, discoveryCount: 4, turns: 15, toolCalls: 30 }),
  makeRun({ id: "PTR-0911-021", status: "completed", strategy: "exploit", scope: "帳號群組增量回溯", startedAt: "2026-09-11 14:00", duration: "07:31", scannedEntities: 3018, discoveryCount: 1, turns: 9, toolCalls: 17 }),
  makeRun({ id: "PTR-0911-020", status: "completed", strategy: "explore", scope: "低頻異常活動樣本", startedAt: "2026-09-11 12:00", duration: "13:26", scannedEntities: 5880, discoveryCount: 2, turns: 16, toolCalls: 31 }),
];

export const patrolApi = {
  async listRuns(): Promise<PatrolRun[]> { return structuredClone(patrolRuns); },
  async getRun(id: string): Promise<PatrolRun | undefined> { return structuredClone(patrolRuns.find((run) => run.id === id)); },
  async listLiveJobs(): Promise<PatrolJobState[]> { return liveJson<PatrolJobState[]>("patrol/jobs?limit=50"); },
  async getLiveJob(id: string): Promise<PatrolJobState> { return liveJson<PatrolJobState>(`patrol/jobs/${encodeURIComponent(id)}`); },
};

async function liveJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api/patrol/${path}`, { cache: "no-store" });
  const body = await response.json().catch(() => ({})) as T & { detail?: string; error?: { message?: string } };
  if (!response.ok) throw new Error(body.error?.message ?? body.detail ?? `Patrol API failed (${response.status})`);
  return body;
}

export interface PatrolEvidence { id: string; source: string; type: string; ref_id?: string | null; observed_at?: string | null; data: Record<string, unknown> }
export interface PatrolJobState {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  run_id: string;
  strategy: "exploit" | "explore";
  policy_ref: { id: string; version: string };
  created_at: string;
  updated_at: string;
  result: null | {
    run_id: string;
    strategy: "exploit" | "explore";
    policy_ref: { id: string; version: string };
    discoveries: Array<{ subject: { type: string; id: string }; hypothesis: string; reason: string; observed_signals: Array<{ name: string; description: string; evidence_refs: string[] }>; counter_signals: string[]; priority: number; evidence_refs: string[] }>;
    evidence: PatrolEvidence[];
  };
  error: string | null;
  handoff_status: "pending" | "not_required" | "delivered" | "failed";
  handoff_attempts: number;
}
