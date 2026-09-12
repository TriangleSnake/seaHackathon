"use client";

import { patrolRuns } from "@/lib/api/patrol";
import { patrolApi } from "@/lib/api/patrol";
import { useDashboardMode } from "@/lib/dashboard-mode";
import { useQuery } from "@tanstack/react-query";
import type { PatrolRunStatus, PatrolStrategy } from "@/types/patrol";
import { AlertTriangle, ChevronLeft, ChevronRight, Clock3, Radar, Search, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

const PAGE_SIZE = 5;
const statusLabel: Record<PatrolRunStatus, string> = { queued: "等待中", completed: "已完成", running: "執行中", failed: "失敗" };
const strategyLabel: Record<PatrolStrategy, string> = { exploit: "Exploit", explore: "Explore" };

export function PatrolContent() {
  const mode = useDashboardMode();
  const live = useQuery({ queryKey: ["patrol-jobs"], queryFn: patrolApi.listLiveJobs, enabled: mode === "live", refetchInterval: 5_000, retry: false });
  const runs = mode === "demo" ? patrolRuns : (live.data ?? []).map((job) => ({
    id: job.job_id,
    status: job.status,
    strategy: job.strategy,
    scope: job.run_id,
    startedAt: new Date(job.created_at).toLocaleString("zh-TW", { hour12: false }),
    duration: "",
    scannedEntities: job.result?.evidence.length ?? 0,
    policyRef: job.policy_ref,
    budget: { turns: { used: 0, limit: 0 }, toolCalls: { used: 0, limit: 0 } },
    discoveries: (job.result?.discoveries ?? []).map((item, index) => ({ id: `${job.job_id}-${index + 1}`, subject: item.subject.id, subjectType: item.subject.type, priority: item.priority >= .8 ? "critical" as const : item.priority >= .6 ? "high" as const : "medium" as const, summary: item.reason, evidenceRefs: item.evidence_refs })),
    activity: [],
  }));
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<PatrolRunStatus | "all">("all");
  const [strategy, setStrategy] = useState<PatrolStrategy | "all">("all");
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => runs.filter((run) => {
    const matchesQuery = !query || `${run.id} ${run.scope}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery && (status === "all" || run.status === status) && (strategy === "all" || run.strategy === strategy);
  }), [runs, query, status, strategy]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const activeFilters = Boolean(query) || status !== "all" || strategy !== "all";
  useEffect(() => setPage(1), [query, status, strategy]);

  const clearFilters = () => { setQuery(""); setStatus("all"); setStrategy("all"); };
  const todayRuns = mode === "demo" ? runs.filter((run) => run.startedAt.startsWith("2026-09-12")) : runs.filter((run) => new Date().toDateString() === new Date((live.data ?? []).find((job) => job.job_id === run.id)?.created_at ?? 0).toDateString());
  const scanned = todayRuns.reduce((total, run) => total + run.scannedEntities, 0);
  const discoveries = todayRuns.reduce((total, run) => total + run.discoveries.length, 0);

  return <div className="patrol-page">
    <div className="page-head"><div><div className="breadcrumb">Autonomous Discovery</div><h1>自主巡查</h1><p>查看排程巡查、發現與完整 Agent 執行紀錄。</p></div></div>
    <div className="patrol-stats">
      <div><Radar/><span>今日巡查</span><strong>{todayRuns.length}</strong></div>
      <div><Search/><span>{mode === "demo" ? "掃描實體" : "證據紀錄"}</span><strong>{scanned.toLocaleString("zh-TW")}</strong></div>
      <div><AlertTriangle/><span>新發現</span><strong>{discoveries}</strong></div>
      <div><Clock3/><span>執行中</span><strong>{runs.filter((run) => run.status === "running").length}</strong></div>
    </div>

    <section className="panel patrol-runs-panel">
      <header><div><span>RUN HISTORY</span><h2>巡查執行紀錄</h2></div><strong>{filtered.length} 筆</strong></header>
      <div className="patrol-toolbar">
        <label><Search size={16}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋 Run ID 或巡查範圍" aria-label="搜尋巡查紀錄"/></label>
        <select value={status} onChange={(event) => setStatus(event.target.value as PatrolRunStatus | "all")} aria-label="執行狀態"><option value="all">所有狀態</option><option value="queued">等待中</option><option value="running">執行中</option><option value="completed">已完成</option><option value="failed">失敗</option></select>
        <select value={strategy} onChange={(event) => setStrategy(event.target.value as PatrolStrategy | "all")} aria-label="巡查策略"><option value="all">所有策略</option><option value="exploit">Exploit</option><option value="explore">Explore</option></select>
        {activeFilters && <button onClick={clearFilters}><X size={15}/>清除</button>}
      </div>

      <div className="patrol-run-head" aria-hidden="true"><span>執行紀錄</span><span>狀態</span><span>策略</span><span>{mode === "demo" ? "掃描實體" : "證據"}</span><span>發現</span><span>開始時間</span><span/></div>
      <div className="patrol-run-list">{live.isPending && mode === "live" ? <div className="patrol-empty" aria-live="polite"><Clock3 className="spin"/><h2>正在讀取 Patrol jobs</h2></div> : live.isError && mode === "live" ? <div className="patrol-empty" role="alert"><AlertTriangle/><h2>Patrol 服務無法連線</h2><p>{live.error instanceof Error ? live.error.message : "無法讀取服務"}</p><button onClick={() => live.refetch()}>重新連線</button></div> : pageItems.length ? pageItems.map((run) => <Link href={`/patrol/${run.id}`} className="patrol-run-row" key={run.id}>
        <div><strong>{run.id}</strong><span>{run.scope}</span></div>
        <span className={`patrol-status ${run.status}`}><i/>{statusLabel[run.status]}</span>
        <span className={`patrol-strategy ${run.strategy}`}>{strategyLabel[run.strategy]}</span>
        <b>{run.scannedEntities.toLocaleString("zh-TW")}</b><b>{run.discoveries.length}</b><time>{run.startedAt}</time><ChevronRight size={17}/>
      </Link>) : <div className="patrol-empty"><Search/><h2>{activeFilters ? "找不到巡查紀錄" : "目前沒有 Patrol jobs"}</h2><p>{activeFilters ? "請調整搜尋條件。" : "服務已連線，尚未建立執行工作。"}</p>{activeFilters && <button onClick={clearFilters}>清除篩選</button>}</div>}</div>

      <footer className="patrol-pagination"><span>第 {page} / {pageCount} 頁 · 每頁 {PAGE_SIZE} 筆</span><nav aria-label="巡查紀錄分頁"><button onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page === 1} aria-label="上一頁"><ChevronLeft size={17}/></button>{Array.from({ length: pageCount }, (_, index) => index + 1).map((value) => <button className={page === value ? "active" : ""} onClick={() => setPage(value)} aria-current={page === value ? "page" : undefined} key={value}>{value}</button>)}<button onClick={() => setPage((value) => Math.min(pageCount, value + 1))} disabled={page === pageCount} aria-label="下一頁"><ChevronRight size={17}/></button></nav></footer>
    </section>
  </div>;
}
