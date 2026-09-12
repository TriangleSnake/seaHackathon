"use client";

import { detectionApi } from "@/lib/api/detection";
import { runtimeComponents } from "@/lib/api/runtime-topology";
import { systemControlApi, type SystemJob } from "@/lib/api/system-control";
import { useDashboardMode } from "@/lib/dashboard-mode";
import type { RuntimeComponent, RuntimeThread } from "@/types/runtime-topology";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowDown, ArrowRight, Bot, Boxes, Braces, CheckCircle2, CircleDot, Code2, Database, GitBranch, Network, Radar, Server, ShieldAlert, ShieldCheck, Waypoints } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

const statusLabel = { running: "運作中", healthy: "在線", degraded: "降級", idle: "待命" } as const;
const threadStatusLabel = { running: "執行中", waiting: "等待", completed: "完成", failed: "失敗" } as const;

function ComponentIcon({ id }: { id: string }) {
  if (id === "environment") return <Database size={18}/>;
  if (id === "detection") return <ShieldAlert size={18}/>;
  if (id === "investigation") return <Waypoints size={18}/>;
  if (id === "patrol") return <Radar size={18}/>;
  if (id === "association") return <Network size={18}/>;
  if (id === "agentgateway") return <GitBranch size={18}/>;
  if (id === "dashboard") return <Boxes size={18}/>;
  if (id === "evolution") return <Activity size={18}/>;
  if (id === "builder") return <Code2 size={18}/>;
  if (id === "governance") return <ShieldCheck size={18}/>;
  return <Server size={18}/>;
}

function ThreadIcon({ kind }: { kind: RuntimeThread["kind"] }) {
  if (kind === "tool") return <Braces size={15}/>;
  if (kind === "agent") return <Bot size={15}/>;
  if (kind === "job") return <GitBranch size={15}/>;
  return <CircleDot size={15}/>;
}

function FlowNode({ component, selected, onClick, compact = false }: { component: RuntimeComponent; selected: boolean; onClick: () => void; compact?: boolean }) {
  const active = component.threads.filter((thread) => thread.status === "running" || thread.status === "waiting").length;
  return <button type="button" className={`fixed-flow-node ${component.status}${selected ? " selected" : ""}${compact ? " compact" : ""}`} onClick={onClick} aria-pressed={selected}>
    <span className="fixed-node-icon"><ComponentIcon id={component.id}/></span>
    <span className="fixed-node-copy"><strong>{component.name}</strong><small>{component.role}</small></span>
    <span className={`fixed-node-state ${component.status}`}><i/>{statusLabel[component.status]}</span>
    <span className="fixed-node-meta"><code>{component.version}</code><b>{active > 0 ? `${active} active` : "待命"}</b></span>
  </button>;
}

function FlowArrow({ label, feedback = false }: { label?: string; feedback?: boolean }) {
  return <div className={`fixed-flow-arrow${feedback ? " feedback" : ""}`} aria-hidden="true"><span>{label}</span><i/><ArrowRight size={15}/></div>;
}

export function RuntimeGraph() {
  const mode = useDashboardMode();
  const [componentId, setComponentId] = useState("investigation");
  const [threadId, setThreadId] = useState(investigationDefaultThread());
  const [clock, setClock] = useState("--:--:--");
  const { data: detectionStatus } = useQuery({ queryKey: ["detection-status"], queryFn: detectionApi.status, refetchInterval: 10_000, retry: false });
  const { data: liveJobs = [] } = useQuery({ queryKey: ["system-jobs"], queryFn: systemControlApi.jobs, enabled: mode === "live", refetchInterval: 5_000, retry: false });
  const { data: liveHealth } = useQuery({ queryKey: ["component-health"], queryFn: async () => { const response = await fetch("/api/components"); if (!response.ok) throw new Error("health unavailable"); return response.json() as Promise<{components:{name:string;status:string;latency_ms:number}[]}>; }, enabled: mode === "live", refetchInterval: 5_000, retry: false });

  useEffect(() => {
    const update = () => setClock(new Date().toLocaleTimeString("zh-TW", { hour12: false }));
    update();
    const interval = window.setInterval(update, 1_000);
    return () => window.clearInterval(interval);
  }, []);

  const components = useMemo(() => runtimeComponents.map((component) => {
    if (mode === "demo") return component;
    const jobs = liveJobs.filter((job) => job.agent === component.id);
    const threads = jobs.map(jobToThread);
    const hasActive = jobs.some((job) => ["queued", "running", "dispatched"].includes(job.status));
    const hasFailure = jobs.some((job) => ["failed", "dead_letter"].includes(job.status));
    const health = liveHealth?.components.find((item) => item.name.toLowerCase().replace(" ", "") === component.id.replace("gateway", "gateway"));
    if (component.id === "detection") return { ...component, status: detectionStatus?.ready ? (hasActive ? "running" as const : "healthy" as const) : "degraded" as const, latencyMs: detectionStatus?.latencyMs, threads };
    if (["patrol", "investigation", "association"].includes(component.id)) return { ...component, status: hasActive ? "running" as const : hasFailure ? "degraded" as const : "idle" as const, latencyMs: undefined, threads };
    if (health) return { ...component, status: health.status === "healthy" ? "healthy" as const : "degraded" as const, latencyMs: health.latency_ms, threads };
    return { ...component, status: component.id === "dashboard" ? "healthy" as const : "idle" as const, latencyMs: undefined, threads: [] };
  }), [detectionStatus, liveHealth, liveJobs, mode]);
  const byId = useMemo(() => Object.fromEntries(components.map((component) => [component.id, component])) as Record<string, RuntimeComponent>, [components]);
  const component = byId[componentId] ?? components[0];
  const thread = component.threads.find((item) => item.id === threadId);

  function selectComponent(id: string) {
    const next = byId[id];
    setComponentId(id);
    setThreadId(next?.threads.find((item) => item.status === "running")?.id ?? next?.threads[0]?.id ?? "");
  }

  const node = (id: string, compact = false) => <FlowNode key={id} component={byId[id]} compact={compact} selected={componentId === id} onClick={() => selectComponent(id)}/>;

  return <section className="panel runtime-graph-section">
    <header className="runtime-graph-header"><div><span className="runtime-title-icon"><Waypoints size={19}/></span><div><small>SYSTEM EXECUTION MAP</small><h2>反詐執行流程</h2><p>固定架構 · 點擊元件查看目前工作</p></div></div><div className="runtime-graph-meta"><span><i/>{mode === "demo" ? "DEMO" : "LIVE"}</span><b>{components.filter((item) => item.status === "running").length} 個元件運作中</b><time>{clock}</time></div></header>

    <div className="runtime-graph-layout"><div className="runtime-fixed-map">
      <section className="fixed-flow-lane primary-lane"><header><span>01</span><div><strong>案件主流程</strong><small>事件進入後，完成偵測、調查並呈現在 Dashboard</small></div></header><div className="fixed-primary-flow">
        {node("environment")}<FlowArrow label="events"/>{node("detection")}<FlowArrow label="DetectionResult"/>{node("investigation")}<FlowArrow label="cases"/>{node("dashboard")}
      </div></section>

      <section className="fixed-flow-lane support-lane"><header><span>02</span><div><strong>調查支援</strong><small>不改變主流程；依案件與策略動態加入訊號、關聯與工具</small></div></header><div className="fixed-support-flow">
        <div>{node("patrol", true)}<span>自主發現</span></div>
        <div>{node("association", true)}<span>關聯證據</span></div>
        <div>{node("agentgateway", true)}<span>核准工具</span></div>
        <div className="support-merge"><i/><ArrowDown size={16}/><strong>提交 Investigation</strong></div>
      </div></section>

      <section className="fixed-flow-lane evolution-lane"><header><span>03</span><div><strong>防禦演化</strong><small>從已完成案件形成候選版本，驗證後才回到運行層</small></div></header><div className="fixed-evolution-input"><span>case outcomes</span><i/><ArrowDown size={15}/></div><div className="fixed-evolution-flow">
        {node("evolution", true)}<FlowArrow feedback/>{node("builder", true)}<FlowArrow feedback/>{node("evaluator", true)}<FlowArrow feedback/>{node("governance", true)}<FlowArrow feedback/>{node("system", true)}
      </div><div className="fixed-policy-return"><ShieldCheck size={15}/><span><strong>Active Defense</strong> 通過治理後，才發布新版 Detection、Investigation、Patrol 與 Association Policy。</span></div></section>

      <div className="runtime-legend"><span><i className="running"/>運作中</span><span><i className="healthy"/>在線</span><span><i className="idle"/>待命</span><span><i className="feedback"/>演化回饋</span></div>
    </div><aside className="runtime-inspector">
      <header><div className="runtime-inspector-icon"><ComponentIcon id={component.id}/></div><div><small>COMPONENT</small><h3>{component.name}</h3><p>{component.role}</p></div><span className={`runtime-component-status ${component.status}`}><i/>{statusLabel[component.status]}</span></header>
      <div className="runtime-component-facts"><div><span>版本</span><code>{component.version}</code></div><div><span>延遲</span><strong>{component.latencyMs ?? "—"} ms</strong></div><div><span>Threads</span><strong>{component.threads.length}</strong></div></div>
      <section className="runtime-tree"><div className="runtime-subhead"><div><span>PROCESS TREE</span><h4>工作執行緒</h4></div><b>{component.threads.filter((item) => item.status === "running").length} RUNNING</b></div>{component.threads.length ? <div className="runtime-tree-list">{component.threads.map((item) => <button className={`${item.id === threadId ? "selected" : ""} depth-${item.depth}`} onClick={() => setThreadId(item.id)} key={item.id}><span className="tree-branch" aria-hidden="true">{item.depth === 0 ? "" : item.depth === 1 ? "├─" : "└─"}</span><span className="tree-kind"><ThreadIcon kind={item.kind}/></span><span><strong>{item.label}</strong><code>{item.id}</code></span><i className={`thread-dot ${item.status}`}/></button>)}</div> : <div className="runtime-empty"><CheckCircle2 size={22}/><strong>目前沒有執行中的工作</strong><span>元件在線並等待下一個任務。</span></div>}</section>
      {thread && <section className="runtime-thread-detail"><div className="runtime-subhead"><div><span>THREAD DETAIL</span><h4>{thread.label}</h4></div><span className={`thread-state ${thread.status}`}><i/>{threadStatusLabel[thread.status]}</span></div><p>{thread.summary}</p><dl><div><dt>Elapsed</dt><dd>{thread.elapsed}</dd></div><div><dt>Trace ID</dt><dd><code>{thread.traceId}</code></dd></div><div><dt>Request ID</dt><dd><code>{thread.requestId}</code></dd></div><div><dt>Started</dt><dd>{thread.startedAt}</dd></div></dl><details><summary><Braces size={15}/>查看 Input / Output</summary><div><label>Input</label><pre>{JSON.stringify(thread.input, null, 2)}</pre><label>Output</label><pre>{JSON.stringify(thread.output, null, 2)}</pre></div></details>{thread.href && <Link href={thread.href}>開啟相關紀錄<ArrowRight size={15}/></Link>}</section>}
    </aside></div>
  </section>;
}

function investigationDefaultThread() { return runtimeComponents.find((item) => item.id === "investigation")?.threads.find((item) => item.status === "running")?.id ?? ""; }

function jobToThread(job: SystemJob): RuntimeThread {
  const status: RuntimeThread["status"] = job.status === "completed" ? "completed" : ["failed", "dead_letter"].includes(job.status) ? "failed" : job.status === "queued" ? "waiting" : "running";
  const subject = job.subject && typeof job.subject.id === "string" ? job.subject.id : job.trigger_ref;
  const caseId = job.result && typeof job.result.case_id === "string" ? job.result.case_id : undefined;
  return {
    id: job.job_id,
    parentId: job.parent_job_id ?? undefined,
    depth: job.parent_job_id ? 1 : 0,
    label: `${job.agent} · ${subject}`,
    kind: "job",
    status,
    startedAt: new Date(job.started_at ?? job.created_at).toLocaleTimeString("zh-TW", { hour12: false }),
    elapsed: job.completed_at ? "已結束" : "進行中",
    traceId: job.job_id,
    requestId: job.trigger_ref,
    summary: job.error ?? `${job.trigger_type} 觸發；attempt ${job.attempt}/${job.max_attempts}`,
    input: { subject: job.subject, payload: job.payload, policy_version: job.policy_version },
    output: job.result ?? { status: job.status },
    href: caseId ? `/cases/${caseId}` : undefined,
  };
}
