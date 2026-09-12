import type { PatrolRun } from "@/types/patrol";
import { Activity, ArrowLeft, ArrowRight, Check, ChevronDown, CircleAlert, Clock3, FileSearch, Gauge, Radar, ShieldCheck } from "lucide-react";
import Link from "next/link";

const statusLabel = { completed: "已完成", running: "執行中", failed: "失敗" } as const;
const activityLabel = { completed: "完成", running: "執行中", failed: "失敗" } as const;

export function PatrolRunDetail({ run }: { run: PatrolRun }) {
  return <div className="patrol-detail-page">
    <Link href="/patrol" className="back-link"><ArrowLeft size={16}/>返回巡查紀錄</Link>
    <div className="patrol-detail-head"><div><div><code>{run.id}</code><span className={`patrol-status ${run.status}`}><i/>{statusLabel[run.status]}</span></div><h1>{run.scope}</h1><p>{run.strategy === "exploit" ? "沿核准模式尋找新的高信心度候選。" : "從活動樣本探索尚未被現有 Detection 涵蓋的模式。"}</p></div><Link href="/policies/patrol" className="button secondary"><ShieldCheck size={16}/>查看 Agent Policy</Link></div>
    <section className="panel patrol-run-summary">
      <div><Radar/><span>策略</span><strong>{run.strategy.toUpperCase()}</strong></div><div><FileSearch/><span>掃描實體</span><strong>{run.scannedEntities.toLocaleString("zh-TW")}</strong></div><div><CircleAlert/><span>有效發現</span><strong>{run.discoveries.length}</strong></div><div><Clock3/><span>執行時間</span><strong>{run.duration}</strong></div>
    </section>
    <div className="patrol-detail-grid"><div className="patrol-detail-main">
      <section className="panel patrol-activity-panel"><header><div><span>AGENT TRACE</span><h2>執行軌跡</h2></div><b>{run.activity.length} STEPS</b></header><div className="patrol-activity-list">{run.activity.map((event) => <details className={`patrol-activity ${event.status}`} open={event.status !== "completed"} key={event.order}><summary><span className="activity-marker">{event.status === "completed" ? <Check size={14}/> : event.order}</span><div><small>STEP {String(event.order).padStart(2, "0")} · {event.agent}</small><strong>{event.action}</strong>{event.tool && <code>{event.tool}</code>}</div><span className={`activity-state ${event.status}`}>{activityLabel[event.status]}</span><time>{event.durationMs ? `${event.durationMs} ms` : "—"}</time><ChevronDown size={17}/></summary><div className="patrol-activity-detail"><div><label>Input</label><pre>{JSON.stringify(event.input, null, 2)}</pre></div><div><label>Output</label><pre>{JSON.stringify(event.output, null, 2)}</pre></div>{event.evidenceRefs.length > 0 && <div className="activity-evidence"><label>Evidence</label><p>{event.evidenceRefs.map((reference) => <code key={reference}>{reference}</code>)}</p></div>}</div></details>)}</div></section>
      <section className="panel patrol-discoveries-panel"><header><div><span>DISCOVERIES</span><h2>本次發現</h2></div><b>{run.discoveries.length} ITEMS</b></header><div className="patrol-discovery-list">{run.discoveries.length ? run.discoveries.map((item) => <article key={item.id}><div className={`priority ${item.priority}`}>{item.priority}</div><div><small>{item.subjectType} · {item.id}</small><strong>{item.subject}</strong><p>{item.summary}</p><div>{item.evidenceRefs.map((reference) => <code key={reference}>{reference}</code>)}</div></div>{item.caseId ? <Link href={`/cases/${item.caseId}`}><span>{item.caseId}</span><ArrowRight size={16}/></Link> : <span className="awaiting-case">等待 Investigation</span>}</article>) : <div className="patrol-empty"><FileSearch/><h2>本次沒有產生發現</h2></div>}</div></section>
    </div><aside className="patrol-detail-side">
      <section className="panel patrol-context"><header><Gauge size={18}/><h2>Run Context</h2></header><dl><div><dt>開始時間</dt><dd>{run.startedAt}</dd></div><div><dt>Policy</dt><dd><code>{run.policyRef.id}</code></dd></div><div><dt>版本</dt><dd><code>{run.policyRef.version}</code></dd></div><div><dt>策略</dt><dd>{run.strategy.toUpperCase()}</dd></div></dl></section>
      <section className="panel patrol-budget"><header><Activity size={18}/><h2>執行預算</h2></header>{[["Agent turns", run.budget.turns], ["Tool calls", run.budget.toolCalls]].map(([label, value]) => { const budget = value as { used: number; limit: number }; return <div className="patrol-budget-row" key={label as string}><div><span>{label as string}</span><b>{budget.used} / {budget.limit}</b></div><i><span style={{ width: `${Math.min(100, budget.used / budget.limit * 100)}%` }}/></i></div>; })}</section>
      <section className="panel patrol-result"><span>RUN RESULT</span><strong>{run.status === "completed" ? "已完成本次巡查" : run.status === "running" ? "Agent 仍在執行" : "執行中斷，可重試"}</strong><p>{run.discoveries.filter((item) => item.caseId).length} 個發現已建立 Case，其餘保留在候選佇列。</p></section>
    </aside></div>
  </div>;
}
