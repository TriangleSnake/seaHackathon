import type { RuntimeComponent, RuntimeConnection, RuntimeThread } from "@/types/runtime-topology";

const investigationThreads: RuntimeThread[] = [
  { id: "thread:case-0841", depth: 0, label: "CASE-2026-0912-0841", kind: "request", status: "running", startedAt: "10:41:08", elapsed: "02:14", traceId: "tr_84f7d2a1", requestId: "req_0912_0841", summary: "Evidence 已蒐集完成，正在彙整最終判定。", input: { subject: "acct_8f3a19", detection_id: "DET-0912-741", scoreboard_config: "v3" }, output: { evidence: 6, findings: 2, fraud_score: 0.91 }, href: "/cases/CASE-2026-0912-0841" },
  { id: "thread:orchestrator-0841", parentId: "thread:case-0841", depth: 1, label: "Investigation Orchestrator", kind: "agent", status: "running", startedAt: "10:41:09", elapsed: "02:13", traceId: "tr_84f7d2a1", requestId: "req_0912_0841", summary: "等待最後一個 Agent 回傳後套用停止規則。", input: { policy_version: "v7", available_agents: 4 }, output: { completed_agents: 3, pending_agents: 1 } },
  { id: "thread:chat-0841", parentId: "thread:orchestrator-0841", depth: 2, label: "Chat Agent", kind: "agent", status: "completed", startedAt: "10:41:12", elapsed: "00:38", traceId: "tr_84f7d2a1", requestId: "req_0912_0841", summary: "確認對話內存在站外付款引導。", input: { conversation_ref: "CHAT-33811" }, output: { finding: "off_platform_payment", evidence_refs: ["EV-0841-03", "EV-0841-04"] } },
  { id: "thread:transaction-0841", parentId: "thread:orchestrator-0841", depth: 2, label: "Transaction Agent", kind: "agent", status: "waiting", startedAt: "10:41:43", elapsed: "01:39", traceId: "tr_84f7d2a1", requestId: "req_0912_0841", summary: "等待 Agent Gateway 的交易活動查詢。", input: { account_id: "acct_8f3a19", window: "30d" }, output: { state: "waiting_for_tool" } },
  { id: "thread:tool-0841", parentId: "thread:transaction-0841", depth: 3, label: "get_account_activity", kind: "tool", status: "running", startedAt: "10:42:54", elapsed: "00:28", traceId: "tr_84f7d2a1", requestId: "req_0912_0841", summary: "透過 Agent Gateway 查詢規範化交易活動。", input: { account_id: "acct_8f3a19", limit: 200 }, output: { rows_received: 148, complete: false } },
  { id: "thread:case-0794", depth: 0, label: "CASE-2026-0912-0794", kind: "request", status: "running", startedAt: "10:42:16", elapsed: "01:06", traceId: "tr_23a51ce0", requestId: "req_0912_0794", summary: "正在驗證關聯證據與歷史案件重疊。", input: { subject: "acct_72de90", detection_id: "DET-0912-728" }, output: { evidence: 3, findings: 1 }, href: "/cases/CASE-2026-0912-0794" },
  { id: "thread:association-0794", parentId: "thread:case-0794", depth: 1, label: "Association Agent", kind: "agent", status: "running", startedAt: "10:42:18", elapsed: "01:04", traceId: "tr_23a51ce0", requestId: "req_0912_0794", summary: "延伸已知實體並建立 evidence-backed relations。", input: { entity_id: "acct_72de90", strategy: "focused" }, output: { entities: 5, relations: 4 } },
  { id: "thread:case-0828", depth: 0, label: "CASE-2026-0912-0828", kind: "request", status: "waiting", startedAt: "10:39:44", elapsed: "03:38", traceId: "tr_5d918cbe", requestId: "req_0912_0828", summary: "等待 Scoreboard 資源配額釋放。", input: { subject: "shop_northstar", scoreboard_config: "v3" }, output: { state: "queued", reason: "agent_concurrency_limit" }, href: "/cases/CASE-2026-0912-0828" },
];

const compactThreads = (component: string, rows: Array<[string, string, RuntimeThread["status"], string?]>): RuntimeThread[] => rows.map(([id, label, status, href], index) => ({ id: `${component}:${id}`, depth: index === 0 ? 0 : 1, parentId: index === 0 ? undefined : `${component}:${rows[0][0]}`, label, kind: index === 0 ? "job" : "agent", status, startedAt: index === 0 ? "10:40:00" : "10:40:02", elapsed: index === 0 ? "03:22" : "03:20", traceId: `tr_${component}_${id}`, requestId: `req_${id}`, summary: `${label} 的執行狀態與最近輸出。`, input: { component, task: label }, output: { status }, href }));

export const runtimeComponents: RuntimeComponent[] = [
  { id: "environment", name: "Environment", role: "事件與業務資料", version: "postgres-16.4", status: "healthy", latencyMs: 8, threads: [] },
  { id: "detection", name: "Detection", role: "即時偵測與觸發", version: "v0.1.0", status: "degraded", threads: [] },
  { id: "investigation", name: "Investigation", role: "證據調度與判定", version: "v0.3.0", status: "running", latencyMs: 42, threads: investigationThreads },
  { id: "patrol", name: "Patrol", role: "自主探索", version: "v0.2.2", status: "running", latencyMs: 186, threads: compactThreads("patrol", [["run-029", "PTR-0912-029", "running", "/patrol/PTR-0912-029"], ["explore", "Explore strategy", "running"], ["evidence", "Evidence validation", "waiting"]]) },
  { id: "association", name: "Association", role: "關聯圖與群組", version: "v0.2.1", status: "running", latencyMs: 27, threads: compactThreads("association", [["job-384", "Association Job 384", "running", "/association"], ["focused", "Focused Agent", "running"], ["callback", "Result callback", "waiting"]]) },
  { id: "agentgateway", name: "Agent Gateway", role: "Agent 工具閘道", version: "v1.5.0", status: "running", latencyMs: 12, threads: compactThreads("gateway", [["mcp-118", "MCP session 118", "running"], ["tool-991", "get_account_activity", "running"], ["tool-988", "get_previous_cases", "completed"]]) },
  { id: "dashboard", name: "Dashboard", role: "人工控制介面", version: "v0.1.0", status: "healthy", latencyMs: 18, threads: [] },
  { id: "evolution", name: "Evolution", role: "模式演化", version: "v0.2.0", status: "running", latencyMs: 38, threads: compactThreads("evolution", [["pattern-044", "PAT-2026-044", "running", "/evolution"], ["synthesis", "Pattern synthesis", "running"], ["counterexample", "Counterexample check", "waiting"]]) },
  { id: "builder", name: "Codex Builder", role: "候選防禦建置", version: "v0.1.8", status: "idle", latencyMs: 54, threads: [] },
  { id: "evaluator", name: "Evaluator", role: "候選版本評估", version: "v0.2.3", status: "idle", latencyMs: 33, threads: [] },
  { id: "governance", name: "Governance", role: "審核與發布閘門", version: "v0.2.1", status: "idle", latencyMs: 24, threads: [] },
  { id: "system", name: "System", role: "Control Plane · Scoreboard", version: "v0.2.1", status: "healthy", latencyMs: 18, threads: [] },
];

export const runtimeConnections: RuntimeConnection[] = [
  { id: "environment-detection", source: "environment", target: "detection", label: "events", kind: "runtime" },
  { id: "detection-investigation", source: "detection", target: "investigation", label: "DetectionResult", kind: "runtime" },
  { id: "patrol-investigation", source: "patrol", target: "investigation", label: "discoveries", kind: "runtime" },
  { id: "association-investigation", source: "association", target: "investigation", kind: "runtime" },
  { id: "gateway-investigation", source: "agentgateway", target: "investigation", label: "tools", kind: "control" },
  { id: "gateway-patrol", source: "agentgateway", target: "patrol", kind: "control" },
  { id: "gateway-association", source: "agentgateway", target: "association", kind: "control" },
  { id: "investigation-dashboard", source: "investigation", target: "dashboard", label: "cases", kind: "runtime" },
  { id: "investigation-evolution", source: "investigation", target: "evolution", kind: "feedback" },
  { id: "evolution-builder", source: "evolution", target: "builder", kind: "feedback" },
  { id: "builder-evaluator", source: "builder", target: "evaluator", kind: "feedback" },
  { id: "evaluator-governance", source: "evaluator", target: "governance", kind: "feedback" },
  { id: "governance-system", source: "governance", target: "system", kind: "feedback" },
  { id: "system-detection", source: "system", target: "detection", label: "active policy", kind: "control" },
];

export const runtimeTopologyApi = {
  async getTopology() { return structuredClone({ components: runtimeComponents, connections: runtimeConnections, observedAt: "2026-09-12T10:43:22+08:00" }); },
};
