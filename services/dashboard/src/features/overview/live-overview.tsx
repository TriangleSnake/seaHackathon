"use client";

import { RuntimeGraph } from "@/features/overview/runtime-graph";
import { systemControlApi } from "@/lib/api/system-control";
import { useQuery } from "@tanstack/react-query";
import { Activity, CircleCheck, Clock3, ServerCrash, Workflow } from "lucide-react";

export function LiveOverview() {
  const { data: jobs = [], isPending, error } = useQuery({ queryKey: ["system-jobs"], queryFn: systemControlApi.jobs, refetchInterval: 5_000, retry: false });
  const active = jobs.filter((job) => ["queued", "running", "dispatched"].includes(job.status)).length;
  const completed = jobs.filter((job) => job.status === "completed").length;
  const failed = jobs.filter((job) => ["failed", "dead_letter"].includes(job.status)).length;

  return <div className="overview-page"><div className="page-head"><div><div className="breadcrumb">Operations / Live backend</div><h1>營運總覽</h1><p>此畫面只呈現 System Control Plane 已回傳的實際資料。</p></div><div className="overview-health"><span/><div><strong>{error ? "Control Plane 無法連線" : "Live data"}</strong><small>{isPending ? "正在讀取" : `最後取得 ${jobs.length} 筆工作`}</small></div></div></div>
    <section className="metric-row" aria-label="工作摘要">
      <div className="metric-card"><Workflow/><span>近期工作</span><strong>{isPending ? "—" : jobs.length}</strong><small>System jobs read model</small></div>
      <div className="metric-card attention"><Activity/><span>執行中／等待</span><strong>{isPending ? "—" : active}</strong><small>每 5 秒更新</small></div>
      <div className="metric-card"><CircleCheck/><span>已完成</span><strong>{isPending ? "—" : completed}</strong><small>實際 job status</small></div>
      <div className="metric-card"><ServerCrash/><span>失敗／Dead letter</span><strong>{isPending ? "—" : failed}</strong><small>不以 Demo 資料補值</small></div>
    </section>
    <RuntimeGraph/>
    <section className="panel review-panel"><div className="section-title"><div><span>RECENT SYSTEM JOBS</span><h2>最近執行</h2><p>案件 read API 尚未提供前，Live 版不顯示模擬案件與趨勢。</p></div></div>
      {error ? <div className="empty-table"><ServerCrash/><h2>無法取得 System jobs</h2><p>{error instanceof Error ? error.message : "System API unavailable"}</p></div> : <div className="review-list">{jobs.slice(0, 8).map((job) => <article className="review-row" key={job.job_id}><div className="review-risk"><strong>{job.attempt}</strong><span>Attempt</span></div><div className="review-main"><div><code>{job.job_id}</code><span className={`thread-state ${job.status === "queued" ? "waiting" : job.status === "failed" || job.status === "dead_letter" ? "failed" : job.status === "completed" ? "completed" : "running"}`}><i/>{job.status}</span></div><strong>{job.agent}</strong><p>{job.trigger_type} · {job.trigger_ref}</p></div><div className="review-meta"><Clock3 size={14}/><span>{new Date(job.updated_at).toLocaleTimeString("zh-TW", { hour12: false })}</span><small>{job.policy_version}</small></div></article>)}</div>}
    </section>
  </div>;
}
