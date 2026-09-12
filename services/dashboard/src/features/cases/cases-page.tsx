"use client";

import { CaseStatusBadge } from "@/components/case-status";
import { cases } from "@/lib/api/cases";
import { systemControlApi, type SystemCase } from "@/lib/api/system-control";
import { useDashboardMode } from "@/lib/dashboard-mode";
import type { FraudCase } from "@/types/case";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Clock3, Search, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

function object(value: unknown): Record<string, unknown> { return value && typeof value === "object" ? value as Record<string, unknown> : {}; }

function caseFromRecord(item: SystemCase): FraudCase {
  const subject = object(item.subject);
  const triggers = Array.isArray(item.detection_result.triggers) ? item.detection_result.triggers : [];
  return { id:item.case_id, subject:String(subject.id ?? object(item.detection_result.subject).id ?? "—"), subjectType:String(subject.type ?? object(item.detection_result.subject).type) === "shop" ? "shop" : "account", status:item.status === "failed" ? "review" : item.status, verdict:item.verdict, fraudScore:typeof item.scoreboard.fraud_score === "number" ? item.scoreboard.fraud_score : undefined, confidence:item.confidence ?? undefined, triggers:triggers.map(value => String(object(value).type ?? object(value).reason ?? "trigger")), updatedAt:new Date(item.updated_at).toLocaleString("zh-TW", { hour12:false }), summary:item.summary ?? item.error ?? (item.status === "investigating" ? "Investigation 正在執行。" : "尚未產生調查結果。"), evidenceCount:item.evidence.length, invokedAgents:item.agents_invoked.map(value => String(value.agent ?? "agent")) };
}

export function CasesContent() {
  const mode = useDashboardMode();
  const live = useQuery({ queryKey:["system-cases"], queryFn:systemControlApi.cases, enabled:mode === "live", refetchInterval:5_000, retry:false });
  const source = mode === "demo" ? cases : (live.data ?? []).map(caseFromRecord);
  const [q,setQ]=useState(""); const [status,setStatus]=useState("all"); const [verdict,setVerdict]=useState("all");
  const items=useMemo(()=>source.filter(item=>(!q||`${item.id} ${item.subject}`.toLowerCase().includes(q.toLowerCase()))&&(status==="all"||item.status===status)&&(verdict==="all"||item.verdict===verdict)),[source,q,status,verdict]);
  const active=status!=="all"||verdict!=="all"||Boolean(q); const clear=()=>{setQ("");setStatus("all");setVerdict("all")};
  return <div className="cases-page"><div className="page-head"><div><div className="breadcrumb">Investigation</div><h1>案件管理</h1><p>{mode==="live"?"System backend 持久化的實際案件。":"搜尋、篩選並檢視展示案件。"}</p></div></div><section className="panel cases-panel"><div className="case-toolbar"><label><Search size={16}/><input value={q} onChange={event=>setQ(event.target.value)} placeholder="搜尋 Case ID 或 Subject" aria-label="搜尋案件"/></label><select value={status} onChange={event=>setStatus(event.target.value)} aria-label="案件狀態"><option value="all">所有狀態</option><option value="review">待審核</option><option value="investigating">調查中</option><option value="fraud">詐欺</option><option value="normal">正常</option></select><select value={verdict} onChange={event=>setVerdict(event.target.value)} aria-label="案件判定"><option value="all">所有判定</option><option value="fraud">詐欺</option><option value="suspicious">可疑</option><option value="normal">正常</option><option value="unknown">未判定</option></select>{active&&<button onClick={clear}><X size={14}/>清除</button>}<span>{items.length} 筆案件</span></div>{mode==="live"&&live.isPending?<div className="empty-table" aria-live="polite"><Clock3 className="spin"/><h2>正在讀取案件資料庫</h2></div>:mode==="live"&&live.isError?<div className="empty-table" role="alert"><AlertTriangle/><h2>案件資料無法連線</h2><p>{live.error instanceof Error?live.error.message:"System API unavailable"}</p><button onClick={()=>live.refetch()}>重新連線</button></div>:items.length?<div className="case-table"><table><thead><tr><th>案件</th><th>狀態</th><th>判定</th><th>Fraud Score</th><th>觸發條件</th><th>更新時間</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{items.map(item=><tr key={item.id}><td><Link href={`/cases/${item.id}`}><strong>{item.id}</strong><span>{item.subject}</span></Link></td><td><CaseStatusBadge value={item.status}/></td><td><CaseStatusBadge value={item.verdict}/></td><td><strong className="table-score">{item.fraudScore?.toFixed(2)??"—"}</strong></td><td><div className="compact-triggers">{item.triggers.slice(0,2).map(trigger=><span key={trigger}>{trigger}</span>)}</div></td><td>{item.updatedAt}</td><td><Link href={`/cases/${item.id}`} aria-label={`查看 ${item.id}`}><ArrowRight size={16}/></Link></td></tr>)}</tbody></table></div>:<div className="empty-table"><Search/><h2>{active?"找不到符合條件的案件":"目前沒有案件"}</h2><p>{active?"調整搜尋字詞或清除篩選條件。":"資料庫已連線，Investigation 建立後會自動出現在這裡。"}</p>{active&&<button onClick={clear}>清除篩選</button>}</div>}</section></div>;
}
