"use client";

import { associationsApi } from "@/lib/api/associations";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Boxes, Clock3, FileSearch, GitBranch, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

const statusLabel = { queued: "等待中", running: "執行中", completed: "已完成", failed: "失敗" } as const;

export function AssociationLive() {
  const query = useQuery({ queryKey: ["association-jobs"], queryFn: associationsApi.listLiveJobs, refetchInterval: 5_000, retry: false });
  const [selectedId, setSelectedId] = useState<string>();
  useEffect(() => { if (!selectedId && query.data?.[0]) setSelectedId(query.data[0].job_id); }, [query.data, selectedId]);
  const selected = query.data?.find((job) => job.job_id === selectedId) ?? query.data?.[0];
  const nodeLabels = useMemo(() => new Map(selected?.result?.nodes.map((node) => [node.id, node.label ?? node.id]) ?? []), [selected]);

  if (query.isPending) return <section className="panel live-connection-state" aria-live="polite"><Clock3 className="spin"/><h2>正在讀取 Association jobs</h2></section>;
  if (query.isError) return <section className="panel live-connection-state" role="alert"><AlertTriangle/><h2>Association 服務無法連線</h2><p>{query.error instanceof Error ? query.error.message : "無法讀取服務"}</p><button className="button secondary" onClick={() => query.refetch()}><RefreshCw size={15}/>重新連線</button></section>;
  if (!query.data?.length) return <section className="panel live-connection-state"><FileSearch/><h2>目前沒有 Association jobs</h2><p>服務已連線，尚未建立關聯分析工作。</p></section>;

  return <div className="association-live-layout">
    <section className="panel association-job-list"><header><div><span>LIVE JOBS</span><h2>關聯分析工作</h2></div><b>{query.data.length}</b></header>{query.data.map((job) => <button key={job.job_id} className={selected?.job_id === job.job_id ? "active" : ""} onClick={() => setSelectedId(job.job_id)}><div><code>{job.job_id}</code><strong>{job.case_id}</strong><small>{new Date(job.created_at).toLocaleString("zh-TW", { hour12: false })}</small></div><span className={`patrol-status ${job.status}`}><i/>{statusLabel[job.status]}</span><ArrowRight size={16}/></button>)}</section>
    {selected && <div className="association-live-main">
      <section className="panel association-live-summary"><header><div><span>ASSOCIATION RESULT</span><h2>{selected.case_id}</h2></div><code>{selected.policy_ref.id}@{selected.policy_ref.version}</code></header><div><span><b>{selected.result?.nodes.length ?? 0}</b>實體</span><span><b>{selected.result?.edges.length ?? 0}</b>關聯</span><span><b>{selected.result?.related_subjects.length ?? 0}</b>相關對象</span><span><b>{selected.result?.evidence.length ?? 0}</b>證據</span></div>{selected.error && <p className="live-inline-error"><AlertTriangle size={16}/>{selected.error}</p>}</section>
      {selected.result?.nodes.length ? <section className="panel association-live-map"><header><div><span>RELATION MAP</span><h2>實際關聯</h2></div><span>{selected.strategy}</span></header><div className="association-node-grid">{selected.result.nodes.map((node) => <article key={node.id}><Boxes size={17}/><div><small>{node.type}</small><strong>{node.label ?? node.id}</strong><code>{node.id}</code></div></article>)}</div>{selected.result.edges.length > 0 && <div className="association-edge-list">{selected.result.edges.map((edge, index) => <article key={`${edge.source}:${edge.target}:${edge.type}:${index}`}><GitBranch size={16}/><div><strong>{nodeLabels.get(edge.source) ?? edge.source} <ArrowRight size={13}/> {nodeLabels.get(edge.target) ?? edge.target}</strong><span>{edge.type} · {edge.relationship}</span></div><b>{Math.round(edge.confidence * 100)}%</b></article>)}</div>}</section> : <section className="panel live-connection-state compact"><GitBranch/><h2>這次執行沒有產生關聯</h2><p>Job 已完成，但 Association service 回傳 0 nodes / 0 edges。</p></section>}
      {!!selected.result?.related_subjects.length && <section className="panel association-subject-list"><header><h2>相關對象</h2></header>{selected.result.related_subjects.map((item) => <article key={`${item.subject.type}:${item.subject.id}`}><div><small>{item.subject.type}</small><strong>{item.subject.id}</strong><p>{item.reason}</p></div><b>{Math.round(item.association_score * 100)}%</b>{selected.case_id.startsWith("CASE-") && <Link href={`/cases/${selected.case_id}`}>查看案件 <ArrowRight size={14}/></Link>}</article>)}</section>}
      {!!selected.result?.evidence.length && <section className="panel live-evidence-panel"><header><div><span>RAW EVIDENCE</span><h2>原始證據</h2></div><b>{selected.result.evidence.length}</b></header>{selected.result.evidence.map((evidence) => <details key={evidence.id}><summary><code>{evidence.id}</code><strong>{evidence.type}</strong><span>{evidence.source}</span></summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>)}</section>}
    </div>}
  </div>;
}
