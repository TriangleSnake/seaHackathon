"use client";

import { CaseStatusBadge } from "@/components/case-status";
import { associationGraph } from "@/lib/api/associations";
import { cases } from "@/lib/api/cases";
import type { AssociationEntity } from "@/types/association";
import { Background, Controls, Handle, MarkerType, MiniMap, type Edge, type Node, type NodeProps, Position, ReactFlow, type ReactFlowInstance } from "@xyflow/react";
import { ArrowRight, Boxes, Focus, GitBranch, Network, Search, Settings2, ShieldCheck, Store, UserRound, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

type GraphNodeData = { label: string; entity: AssociationEntity; isFocus: boolean };
type GraphNode = Node<GraphNodeData, "associationEntity">;
type Selection = { kind: "entity"; id: string } | { kind: "relation"; id: string };

const positions = [
  { x: 455, y: 24 },
  { x: 455, y: 190 },
  { x: 455, y: 356 },
  { x: 760, y: 105 },
  { x: 760, y: 300 },
];

function positionEntity(index: number, isFocus: boolean) {
  return isFocus ? { x: 90, y: 190 } : positions[index] ?? { x: 760, y: 300 + index * 140 };
}

function priorityTone(score?: number) {
  if (score === undefined) return "unknown";
  if (score >= 0.8) return "critical";
  if (score >= 0.6) return "elevated";
  return "observed";
}

function priorityLabel(score?: number) {
  if (score === undefined) return "未評估";
  if (score >= 0.8) return "高優先";
  if (score >= 0.6) return "待查證";
  return "已觀測";
}

function EntityIcon({ type }: { type?: string }) {
  if (type === "商店") return <Store size={17}/>;
  if (type === "帳號") return <UserRound size={17}/>;
  return <Boxes size={17}/>;
}

function AssociationNode({ data, selected }: NodeProps<GraphNode>) {
  const score = data.entity.riskScore;
  return <div className={`association-node-card ${priorityTone(score)}${data.isFocus ? " focus" : ""}${selected ? " selected" : ""}`}>
    <Handle type="target" position={Position.Left} className="association-handle"/>
    <div className="association-node-head"><span className="association-node-icon"><EntityIcon type={data.entity.entityType}/></span><span className="association-node-type">{data.entity.entityType ?? "實體"}</span>{data.isFocus && <b>核心</b>}</div>
    <strong>{data.label}</strong>
    <div className="association-node-meta"><span><i/>{priorityLabel(score)}</span><code>{score?.toFixed(2) ?? "—"}</code><small>{data.entity.caseIds.length} cases</small></div>
    <Handle type="source" position={Position.Right} className="association-handle"/>
  </div>;
}

const nodeTypes = { associationEntity: AssociationNode };

export function AssociationGraph() {
  const [selection, setSelection] = useState<Selection>({ kind: "entity", id: associationGraph.focusEntityId });
  const [threshold, setThreshold] = useState(0.65);
  const [query, setQuery] = useState("");
  const [flow, setFlow] = useState<ReactFlowInstance<GraphNode, Edge> | null>(null);

  const nodes = useMemo<GraphNode[]>(() => {
    let relatedIndex = 0;
    return associationGraph.entities.map((entity) => {
      const isFocus = entity.id === associationGraph.focusEntityId;
      const index = isFocus ? 0 : relatedIndex++;
      const matches = !query || `${entity.label} ${entity.entityType ?? ""} ${entity.caseIds.join(" ")}`.toLowerCase().includes(query.toLowerCase());
      return {
        id: entity.id,
        type: "associationEntity",
        position: positionEntity(index, isFocus),
        data: { label: entity.label, entity, isFocus },
        className: matches ? "" : "graph-node-muted",
        selected: selection.kind === "entity" && selection.id === entity.id,
        ariaLabel: `${entity.entityType ?? "實體"} ${entity.label}，${priorityLabel(entity.riskScore)}`,
      };
    });
  }, [query, selection]);

  const edges = useMemo<Edge[]>(() => associationGraph.relations
    .filter((relation) => (relation.confidence ?? 1) >= threshold)
    .map((relation) => {
      const selected = selection.kind === "relation" && selection.id === relation.id;
      const confidence = relation.confidence ?? 0;
      return {
        id: relation.id,
        source: relation.source,
        target: relation.target,
        type: "smoothstep",
        label: relation.confidence === undefined ? undefined : `${Math.round(relation.confidence * 100)}%`,
        data: { relation },
        className: selected ? "association-edge selected" : "association-edge",
        style: { stroke: selected ? "#b7d0e4" : "#536f85", strokeWidth: selected ? 2.6 : 1.4 + confidence },
        labelStyle: { fill: selected ? "#e2edf5" : "#a4b5c2", fontSize: 12, fontWeight: 600 },
        labelBgStyle: { fill: "#111922", fillOpacity: 0.96 },
        labelBgPadding: [6, 4] as [number, number],
        markerEnd: { type: MarkerType.ArrowClosed, color: selected ? "#b7d0e4" : "#536f85", width: 16, height: 16 },
      };
    }), [selection, threshold]);

  const selectedEntity = selection.kind === "entity" ? associationGraph.entities.find((entity) => entity.id === selection.id) : undefined;
  const selectedRelation = selection.kind === "relation" ? associationGraph.relations.find((relation) => relation.id === selection.id) : undefined;
  const entityById = new Map(associationGraph.entities.map((entity) => [entity.id, entity]));
  const selectedLabel = selectedEntity?.label ?? (selectedRelation ? `${entityById.get(selectedRelation.source)?.label ?? selectedRelation.source} → ${entityById.get(selectedRelation.target)?.label ?? selectedRelation.target}` : "");
  const relatedCaseIds = selectedEntity?.caseIds ?? selectedRelation?.caseIds ?? [];
  const relatedCases = cases.filter((item) => relatedCaseIds.includes(item.id));
  const evidenceRefs = selectedEntity?.evidenceRefs ?? selectedRelation?.evidenceRefs ?? [];
  const directRelations = selectedEntity ? associationGraph.relations.filter((relation) => relation.source === selectedEntity.id || relation.target === selectedEntity.id).length : undefined;
  const uniqueCaseCount = new Set(associationGraph.entities.flatMap((entity) => entity.caseIds)).size;

  return <div className="association-layout">
    <section className="panel graph-panel">
      <header className="association-graph-head"><div><span className="association-graph-icon"><Network size={19}/></span><div><small>ASSOCIATION MAP</small><h2>案件關聯圖</h2></div></div><div className="graph-head-actions"><div className="graph-run-context"><span>{associationGraph.strategy}</span><code>{associationGraph.policyRef.version}</code></div><Link href="/policies/association" className="association-policy-link"><Settings2 size={15}/>Policy</Link></div></header>

      <div className="association-summary"><div><strong>{associationGraph.entities.length}</strong><span>實體</span></div><div><strong>{associationGraph.relations.length}</strong><span>關聯</span></div><div><strong>{uniqueCaseCount}</strong><span>相關案件</span></div><div><strong>{Math.round(Math.max(...associationGraph.relations.map((relation) => relation.confidence ?? 0)) * 100)}%</strong><span>最高信心度</span></div></div>

      <div className="graph-toolbar"><label><Search size={16}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋實體或 Case ID" aria-label="搜尋關聯實體或案件"/></label><label className="confidence-control"><span>最低信心度</span><input type="range" min="0.5" max="1" step="0.05" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))}/><b>{Math.round(threshold * 100)}%</b></label></div>

      <div className="graph-canvas">
        <ReactFlow<GraphNode, Edge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.16, minZoom: 0.38, maxZoom: 0.9 }}
          minZoom={0.32}
          maxZoom={1.6}
          onlyRenderVisibleElements
          onInit={setFlow}
          onNodeClick={(_, node) => setSelection({ kind: "entity", id: node.id })}
          onEdgeClick={(_, edge) => setSelection({ kind: "relation", id: edge.id })}
          aria-label="實體關聯圖"
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#243341" gap={28} size={1}/>
          <Controls position="top-right" showInteractive={false}/>
          <MiniMap position="bottom-right" pannable zoomable nodeStrokeWidth={3} nodeColor={(node) => { const data = node.data as GraphNodeData; return data.isFocus ? "#7aa2bf" : priorityTone(data.entity.riskScore) === "critical" ? "#a46064" : "#58758a"; }}/>
        </ReactFlow>
        <div className="graph-legend"><span><i className="focus"/>核心實體</span><span><i className="related"/>關聯實體</span><span><GitBranch size={14}/>線條可點選</span><b>{edges.length} / {associationGraph.relations.length} 條顯示中</b></div>
      </div>
    </section>

    <aside className="panel graph-detail">
      {selectedLabel ? <>
        <header><div className="graph-detail-heading"><span className="detail-entity-icon">{selectedEntity ? <EntityIcon type={selectedEntity.entityType}/> : <GitBranch size={17}/>}</span><div><small>{selectedEntity ? selectedEntity.entityType ?? "ENTITY" : "RELATION"}</small><h2>{selectedLabel}</h2></div></div><button onClick={() => setSelection({ kind: "entity", id: associationGraph.focusEntityId })} aria-label="回到核心實體"><X size={18}/></button></header>
        <div className={`entity-risk ${priorityTone(selectedEntity?.riskScore ?? selectedRelation?.confidence)}`}><div><span>{selectedEntity ? "調查優先度" : "關聯信心度"}</span><strong>{selectedEntity ? priorityLabel(selectedEntity.riskScore) : "Evidence backed"}</strong></div><b>{(selectedEntity?.riskScore ?? selectedRelation?.confidence)?.toFixed(2) ?? "—"}</b></div>
        <dl className="entity-facts">
          {directRelations !== undefined && <div><dt>直接關聯</dt><dd>{directRelations}</dd></div>}
          <div><dt>相關案件</dt><dd>{relatedCases.length}</dd></div>
          <div><dt>證據</dt><dd>{evidenceRefs.length}</dd></div>
          {selectedEntity?.firstObserved && <div><dt>首次觀測</dt><dd>{selectedEntity.firstObserved}</dd></div>}
        </dl>
        <section className="related-cases"><h3>相關案件</h3>{relatedCases.length ? relatedCases.map((item) => <Link href={`/cases/${item.id}`} key={item.id} className="related-case-link"><div><code>{item.id}</code><strong>{item.subject}</strong></div><div><CaseStatusBadge value={item.status}/><ArrowRight size={15}/></div></Link>) : <p className="detail-empty">沒有相關案件</p>}</section>
        {evidenceRefs.length > 0 && <section className="relation-evidence"><h3>證據引用</h3>{evidenceRefs.map((reference) => <span key={reference}>{reference}</span>)}</section>}
        {selectedEntity && <button className="center-action" onClick={() => flow?.fitView({ nodes: [{ id: selectedEntity.id }], duration: 350, maxZoom: 1.15, padding: 0.55 })} disabled={!flow}><Focus size={16}/>聚焦此實體</button>}
      </> : <div className="empty-selection"><ShieldCheck/><h2>選擇實體或關聯</h2></div>}
    </aside>
  </div>;
}
