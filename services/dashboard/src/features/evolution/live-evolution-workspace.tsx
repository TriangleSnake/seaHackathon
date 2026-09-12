"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, AlertCircle, Check, ChevronRight, Clock3, GitCommitHorizontal, LoaderCircle, ShieldCheck } from "lucide-react";

type RunEvent = { event_id:string; stage:string; component:string; status:string; summary:string|null; details:Record<string,unknown>; started_at:string; completed_at:string|null };
type Run = { run_id:string; state:string; trigger_type:string; target_policy:string|null; candidate_id:string|null; evaluation_id:string|null; current_stage:string; progress:number; error:string|null; details:Record<string,unknown>; events:RunEvent[]; created_at:string; updated_at:string };
type Version = { version:string; status:string; base_version:string|null; candidate_id:string|null; evaluation_id:string|null; policies:Array<Record<string,unknown>>; metrics:Record<string,unknown>; created_at:string };

const stages = [
  { key:"received", label:"Received", owner:"Evolution" },
  { key:"diagnosing", label:"Diagnose", owner:"Planner" },
  { key:"building", label:"Build", owner:"Candidate Builder" },
  { key:"validating", label:"Evaluate", owner:"Evaluator" },
  { key:"awaiting_approval", label:"Review", owner:"Governance" },
  { key:"active", label:"Activate", owner:"Defense Version" },
] as const;
const stageAliases:Record<string,string> = { proposed:"diagnosing", approved:"awaiting_approval", rejected:"awaiting_approval", failed:"validating" };

async function get<T>(path:string):Promise<T> { const response=await fetch(`/api/evolution/${path}`); if(!response.ok) throw new Error("Evolution API 無法連線"); return response.json(); }
function formatTime(value:string) { return new Intl.DateTimeFormat("zh-TW",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(value)); }
function displayValue(value:unknown) { if(value==null||value==="") return "—"; if(typeof value==="object") return JSON.stringify(value); return String(value); }

const demoData:{runs:Run[];versions:Version[]}={
  runs:[{run_id:"EVO-0912-17",state:"VALIDATING",trigger_type:"pattern_discovered",target_policy:"detection",candidate_id:"CAND-044",evaluation_id:"EVAL-0912-18",current_stage:"validating",progress:64,error:null,details:{pattern_ref:"PAT-2026-044",reason:"偵測到新的詐欺模式"},created_at:"2026-09-12T08:42:00Z",updated_at:"2026-09-12T09:48:00Z",events:[
    {event_id:"EVT-DEMO-01",stage:"received",component:"evolution",status:"completed",summary:"Pattern Spec accepted.",details:{},started_at:"2026-09-12T08:42:00Z",completed_at:"2026-09-12T08:42:02Z"},
    {event_id:"EVT-DEMO-02",stage:"diagnosing",component:"planner",status:"completed",summary:"Defense gap and affected policy identified.",details:{},started_at:"2026-09-12T08:42:03Z",completed_at:"2026-09-12T08:44:31Z"},
    {event_id:"EVT-DEMO-03",stage:"building",component:"candidate_builder",status:"completed",summary:"Candidate CAND-044 built from Detection Policy v8.",details:{},started_at:"2026-09-12T08:44:32Z",completed_at:"2026-09-12T08:51:10Z"},
    {event_id:"EVT-DEMO-04",stage:"validating",component:"evaluator",status:"running",summary:"8,420 / 10,000 evaluation cases completed.",details:{},started_at:"2026-09-12T08:51:11Z",completed_at:null},
  ]}],
  versions:[
    {version:"v13",status:"candidate",base_version:"v12",candidate_id:"CAND-044",evaluation_id:"EVAL-0912-18",policies:[{agent:"detection",version:"v9"},{agent:"investigation",version:"v8"},{agent:"association",version:"v5"}],metrics:{precision:"94.1%",recall:"89.3%",false_positive:"3.2%"},created_at:"2026-09-12T09:48:00Z"},
    {version:"v12",status:"active",base_version:"v11",candidate_id:"CAND-041",evaluation_id:"EVAL-0912-14",policies:[{agent:"detection",version:"v8"},{agent:"investigation",version:"v7"},{agent:"association",version:"v4"}],metrics:{precision:"92.0%",recall:"84.0%",false_positive:"4.2%"},created_at:"2026-09-08T16:20:00Z"},
  ],
};

export function LiveEvolutionWorkspace({mode="live"}:{mode?:"live"|"demo"}) {
  const [selectedRunId,setSelectedRunId]=useState<string|null>(null);
  const query=useQuery({queryKey:["evolution-workspace",mode],queryFn:async()=>{if(mode==="demo")return demoData;const[runs,versions]=await Promise.all([get<Run[]>("evolution/runs"),get<Version[]>("defense-versions")]);return{runs,versions}},refetchInterval:mode==="live"?5000:false,retry:false});
  useEffect(()=>{if(!selectedRunId&&query.data?.runs[0])setSelectedRunId(query.data.runs[0].run_id)},[query.data?.runs,selectedRunId]);
  const selectedRun=useMemo(()=>query.data?.runs.find(run=>run.run_id===selectedRunId)??query.data?.runs[0],[query.data?.runs,selectedRunId]);
  const activeVersion=query.data?.versions.find(version=>version.status.toLowerCase()==="active");

  return <div className="evolution-live">
    <div className="page-head"><div><div className="breadcrumb">AUTONOMOUS DEFENSE / {mode.toUpperCase()}</div><h1>Evolution</h1></div></div>
    {query.isError?<section className="panel empty-table"><AlertCircle/><h2>Evolution API 無法連線</h2><p>{query.error instanceof Error?query.error.message:"Unavailable"}</p></section>:<>
      <section className="evo-summary" aria-label="Evolution 摘要"><div><span>RUNS</span><strong>{query.data?.runs.length??0}</strong></div><div><span>ACTIVE VERSION</span><strong>{activeVersion?.version??"—"}</strong></div><div><span>CURRENT STAGE</span><strong>{selectedRun?.current_stage??"—"}</strong></div></section>
      <div className="evo-workspace">
        <section className="panel evo-run-panel"><header className="evo-section-head"><div><span>EXECUTION QUEUE</span><h2>演化執行</h2></div><b>{query.data?.runs.length??0}</b></header>
          {query.isPending?<div className="empty-table"><LoaderCircle className="spin"/><span>讀取中</span></div>:query.data?.runs.length?<div className="evo-run-list">{query.data.runs.map(run=><button type="button" className={`evo-run-button ${selectedRun?.run_id===run.run_id?"is-selected":""}`} key={run.run_id} onClick={()=>setSelectedRunId(run.run_id)}><div><strong>{run.target_policy??run.trigger_type}</strong><span>{formatTime(run.updated_at)}</span></div><code>{run.run_id}</code><div className="evo-run-state"><span>{run.state}</span><b>{run.progress}%</b></div><div className="evo-progress"><i style={{width:`${run.progress}%`}}/></div></button>)}</div>:<div className="empty-table"><Activity/><h2>尚無 Evolution run</h2></div>}
        </section>
        <section className="panel evo-detail-panel">{selectedRun?<>
          <header className="evo-detail-head"><div><span>SELECTED RUN</span><h2>{selectedRun.run_id}</h2></div><span className={`evo-status evo-status-${selectedRun.state.toLowerCase()}`}>{selectedRun.state}</span></header>
          {selectedRun.state==="RECEIVED"&&<div className="evo-notice"><Clock3/><div><strong>等待 Planner 取得工作</strong><span>工作已保存，但目前沒有後續 stage 紀錄。</span></div></div>}
          {selectedRun.error&&<div className="evo-notice is-error"><AlertCircle/><div><strong>執行失敗</strong><span>{selectedRun.error}</span></div></div>}
          <div className="evo-stage-track">{stages.map((stage,index)=>{const current=stageAliases[selectedRun.current_stage]??selectedRun.current_stage;const currentIndex=stages.findIndex(item=>item.key===current);const done=index<currentIndex||selectedRun.state==="ACTIVE";const active=index===currentIndex;return <div className={`evo-stage ${done?"is-done":""} ${active?"is-current":""}`} key={stage.key}><div className="evo-stage-node">{done?<Check/>:<span>{index+1}</span>}</div><div><strong>{stage.label}</strong><span>{stage.owner}</span></div>{index<stages.length-1&&<ChevronRight className="evo-stage-arrow"/>}</div>})}</div>
          <div className="evo-detail-grid"><div><span>Trigger</span><strong>{selectedRun.trigger_type}</strong></div><div><span>Target</span><strong>{selectedRun.target_policy??"—"}</strong></div><div><span>Candidate</span><strong>{selectedRun.candidate_id??"—"}</strong></div><div><span>Evaluation</span><strong>{selectedRun.evaluation_id??"—"}</strong></div></div>
          <div className="evo-subsection"><h3>Execution events</h3>{selectedRun.events.length?<div className="evo-event-list">{selectedRun.events.map(event=><article key={event.event_id}><div className={`evo-event-dot is-${event.status}`}/><div><strong>{event.component} · {event.stage}</strong><span>{event.summary??"No summary"}</span></div><time>{formatTime(event.started_at)}</time></article>)}</div>:<div className="evo-inline-empty">尚無 stage event</div>}</div>
          {Object.keys(selectedRun.details).length>0&&<div className="evo-subsection"><h3>Run details</h3><dl className="evo-details">{Object.entries(selectedRun.details).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>)}</dl></div>}
        </>:<div className="empty-table"><Activity/><h2>選擇一筆執行</h2></div>}</section>
      </div>
      <section id="defense-versions" className="panel evo-version-panel"><header className="evo-section-head"><div><span>DEFENSE VERSION REGISTRY</span><h2>防禦版本</h2></div><b>{query.data?.versions.length??0}</b></header>
        {query.data?.versions.length?<div className="evo-version-grid">{query.data.versions.map(version=><article key={version.version} className={version.status.toLowerCase()==="active"?"is-active":""}><header><ShieldCheck/><div><h3>{version.version}</h3><span>{formatTime(version.created_at)}</span></div><b>{version.status}</b></header><div className="evo-version-meta"><span>Base <strong>{version.base_version??"—"}</strong></span><span>Candidate <strong>{version.candidate_id??"—"}</strong></span></div><div className="evo-policy-list">{version.policies.length?version.policies.map((policy,index)=><div key={`${version.version}-${index}`}><GitCommitHorizontal/><span>{displayValue(policy.agent??policy.type??`Policy ${index+1}`)}</span><strong>{displayValue(policy.version??policy.ref)}</strong></div>):<span className="evo-inline-empty">尚無 policy snapshot</span>}</div><div className="evo-metrics">{Object.keys(version.metrics).length?Object.entries(version.metrics).map(([key,value])=><span key={key}>{key}<strong>{displayValue(value)}</strong></span>):<span className="evo-inline-empty">尚無 evaluation metrics</span>}</div></article>)}</div>:<div className="empty-table"><ShieldCheck/><h2>尚無 Defense Version</h2></div>}
      </section>
    </>}
  </div>;
}
