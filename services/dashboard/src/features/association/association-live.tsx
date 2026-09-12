"use client";

import { associationsApi } from "@/lib/api/associations";
import { useQuery } from "@tanstack/react-query";
import { AssociationGraph } from "@/features/association/association-graph";
import type { AssociationGraphResponse } from "@/types/association";
import { AlertTriangle, Clock3, FileSearch, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const statusLabel = { queued: "等待中", running: "執行中", completed: "已完成", failed: "失敗" } as const;

export function AssociationLive() {
  const query = useQuery({ queryKey: ["association-jobs"], queryFn: associationsApi.listLiveJobs, refetchInterval: 5_000, retry: false });
  const [selectedId, setSelectedId] = useState<string>();
  useEffect(() => { if (!selectedId && query.data?.[0]) setSelectedId(query.data[0].job_id); }, [query.data, selectedId]);
  const selected = query.data?.find((job) => job.job_id === selectedId) ?? query.data?.[0];
  const graph = useMemo<AssociationGraphResponse | null>(() => {
    if (!selected?.result?.nodes.length) return null;
    const relatedScores = new Map(selected.result.related_subjects.map((item) => [item.subject.id, item.association_score]));
    const evidenceByNode = new Map<string, Set<string>>();
    for (const edge of selected.result.edges) {
      for (const id of [edge.source, edge.target]) {
        const refs = evidenceByNode.get(id) ?? new Set<string>();
        edge.evidence_refs.forEach((ref) => refs.add(ref));
        evidenceByNode.set(id, refs);
      }
    }
    const focusEntityId = selected.result.related_subjects[0]?.relation_paths[0]?.nodes[0]
      ?? selected.result.edges[0]?.source
      ?? selected.result.nodes[0].id;
    return {
      focusEntityId,
      strategy: selected.result.strategy,
      policyRef: selected.result.policy_ref,
      entities: selected.result.nodes.map((node) => ({
        id: node.id,
        label: node.label ?? node.id,
        entityType: node.type,
        riskScore: node.id === focusEntityId ? undefined : node.association_score ?? relatedScores.get(node.id),
        assessmentReason: node.assessment_reason ?? undefined,
        firstObserved: selected.result?.edges.find((edge) => edge.source === node.id || edge.target === node.id)?.first_seen_at ?? undefined,
        caseIds: [selected.case_id],
        evidenceRefs: [...(evidenceByNode.get(node.id) ?? [])],
      })),
      relations: selected.result.edges.map((edge, index) => ({
        id: `${selected.job_id}:edge:${index}`,
        source: edge.source,
        target: edge.target,
        confidence: edge.confidence,
        caseIds: [selected.case_id],
        evidenceRefs: edge.evidence_refs,
      })),
    };
  }, [selected]);

  if (query.isPending) return <section className="panel live-connection-state" aria-live="polite"><Clock3 className="spin"/><h2>正在讀取 Association jobs</h2></section>;
  if (query.isError) return <section className="panel live-connection-state" role="alert"><AlertTriangle/><h2>Association 服務無法連線</h2><p>{query.error instanceof Error ? query.error.message : "無法讀取服務"}</p><button className="button secondary" onClick={() => query.refetch()}><RefreshCw size={15}/>重新連線</button></section>;
  if (!query.data?.length) return <section className="panel live-connection-state"><FileSearch/><h2>目前沒有 Association jobs</h2><p>服務已連線，尚未建立關聯分析工作。</p></section>;

  return <div className="association-live-unified">
    <section className="panel association-live-picker">
      <label htmlFor="association-job">關聯分析工作</label>
      <select id="association-job" value={selected?.job_id ?? ""} onChange={(event) => setSelectedId(event.target.value)}>
        {query.data.map((job) => <option key={job.job_id} value={job.job_id}>{job.case_id} · {statusLabel[job.status]}</option>)}
      </select>
      {selected && <span className={`patrol-status ${selected.status}`}><i/>{statusLabel[selected.status]}</span>}
      <button className="button secondary" onClick={() => query.refetch()} aria-label="重新整理關聯工作"><RefreshCw size={15}/>重新整理</button>
    </section>
    {selected?.error && <p className="live-inline-error"><AlertTriangle size={16}/>{selected.error}</p>}
    {graph ? <AssociationGraph key={selected?.job_id} graph={graph}/> : <section className="panel live-connection-state compact"><FileSearch/><h2>這次執行尚未產生關聯圖</h2><p>{selected?.status === "completed" ? "Job 已完成，但回傳 0 nodes / 0 edges。" : "等待 Association Agent 完成分析。"}</p></section>}
  </div>;
}
