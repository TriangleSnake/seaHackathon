"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Check, ChevronRight, Clock3, Copy, FilePlus2, History, Info, LoaderCircle, RotateCcw, Save, Scale, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { scoreboardApi } from "@/lib/api/scoreboard";
import type { ScoreboardConfig } from "@/types/scoreboard";

const agentLabels = { chat_agent: "Chat Agent", order_agent: "Order Agent", shop_agent: "Shop Agent" };
const nf = new Intl.NumberFormat("zh-TW");

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className={`switch ${checked ? "checked" : ""}`} onClick={() => onChange(!checked)}><span/></button>;
}

function Field({ label, value, onChange, step = "1", min = "0", max, suffix }: { label: string; value: number | string; onChange: (v: string) => void; step?: string; min?: string; max?: string; suffix?: string }) {
  const id = label.replaceAll(" ", "-");
  return <label className="field" htmlFor={id}><span>{label}</span><div className="input-wrap"><input id={id} type="number" value={value} step={step} min={min} max={max} onChange={(e) => onChange(e.target.value)}/>{suffix && <b>{suffix}</b>}</div></label>;
}

function BudgetBar({ label, used, max, unit }: { label: string; used: number; max: number; unit?: string }) {
  const pct = Math.round((used / max) * 100);
  return <div className="budget-row"><div><span>{label}</span><strong>{unit === "$" ? `$${used.toFixed(2)} / $${max.toFixed(2)}` : `${nf.format(used)} / ${nf.format(max)}`}</strong></div><div className="bar"><span style={{ width: `${pct}%` }}/></div><small>{pct}%</small></div>;
}

export function ScoreboardPage() {
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["scoreboard-configs"], queryFn: scoreboardApi.list });
  const active = data?.find((item) => item.status === "active");
  const [draft, setDraft] = useState<ScoreboardConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [toast, setToast] = useState("");
  useEffect(() => { if (active && !draft) setDraft(structuredClone(active)); }, [active, draft]);
  const mutation = useMutation({ mutationFn: scoreboardApi.create, onSuccess: (result) => { setDialog(false); setDirty(false); setToast(`Scoreboard v${result.version} 草稿已建立`); setTimeout(() => setToast(""), 4000); } });

  const update = (path: string, value: number | boolean | string) => {
    if (!draft) return;
    const next = structuredClone(draft); const keys = path.split("."); let cursor: Record<string, unknown> = next as unknown as Record<string, unknown>;
    keys.slice(0, -1).forEach((key) => { cursor = cursor[key] as Record<string, unknown>; }); cursor[keys.at(-1)!] = value;
    setDraft(next); setDirty(true);
  };
  const updateAgent = (index: number, key: "enabled" | "priority" | "costWeight", value: boolean | number) => { if (!draft) return; const next = structuredClone(draft); next.agents[index][key] = value as never; setDraft(next); setDirty(true); };
  const submit = () => { if (draft) mutation.mutate({ ...draft, version: Math.max(...(data?.map((x) => x.version) ?? [0])) + 1, createdAt: new Date().toISOString(), createdBy: "You", note: "待審核的設定調整" }); };

  if (isLoading) return <div className="loading" aria-live="polite"><LoaderCircle className="spin"/>載入 Scoreboard 設定…</div>;
  if (isError || !draft || !active) return <div className="error-state"><AlertTriangle/><h2>無法載入設定</h2><p>請確認 API 服務狀態後重試。</p><button onClick={() => refetch()}>重新載入</button></div>;

  return <AppContent>
    <div className="page-head"><div><div className="breadcrumb">政策控制台 <ChevronRight size={14}/> Scoreboard</div><h1>Scoreboard</h1><p>集中管理調查評分、資源預算與停止條件。所有變更都會建立可稽核的新版本。</p></div><div className="head-actions"><button className="button secondary"><History size={17}/>版本紀錄</button><button className="button primary" disabled={!dirty} onClick={() => setDialog(true)}><FilePlus2 size={17}/>建立新版本</button></div></div>

    <section className="active-banner" aria-label="目前啟用設定"><div className="active-icon"><ShieldCheck/></div><div className="active-title"><span><i/>目前啟用</span><h2>Scoreboard Config v{active.version}</h2><p>採用 Scoring Policy {active.scoringPolicyVersion} · 更新於 2026/09/11 16:42</p></div><div className="active-meta"><div><span>詐欺門檻</span><strong>{active.fraudThreshold.toFixed(2)}</strong></div><div><span>正常門檻</span><strong>{active.normalThreshold.toFixed(2)}</strong></div><div><span>每案成本上限</span><strong>${active.budgets.maxCostUsd.toFixed(2)}</strong></div></div><button className="copy-button" aria-label="複製設定 ID"><Copy size={15}/> scb_003</button></section>

    <div className="notice"><Info size={18}/><div><strong>你正在編輯 v{active.version} 的副本</strong><span>儲存時會建立新版本；現行生產設定不會被直接覆寫。</span></div>{dirty && <b>尚未儲存</b>}</div>

    <form onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <div className="content-grid">
        <div className="form-stack">
          <section className="panel"><div className="panel-head"><div><span className="section-index">01</span><div><h2>評分規則</h2><p>定義調查結果的判定界線。</p></div></div><span className="policy-tag">Scoring Policy {draft.scoringPolicyVersion}</span></div><div className="field-grid"><label className="field"><span>Scoring Policy Version</span><select value={draft.scoringPolicyVersion} onChange={(e) => update("scoringPolicyVersion", e.target.value)}><option>v5</option><option>v4</option><option>v3</option></select></label><Field label="Fraud Threshold" value={draft.fraudThreshold} step="0.01" max="1" onChange={(v) => update("fraudThreshold", Number(v))}/><Field label="Normal Threshold" value={draft.normalThreshold} step="0.01" max="1" onChange={(v) => update("normalThreshold", Number(v))}/></div><div className="threshold"><div className="threshold-labels"><span>正常 ≤ {draft.normalThreshold.toFixed(2)}</span><span>需要調查</span><span>詐欺 ≥ {draft.fraudThreshold.toFixed(2)}</span></div><div className="threshold-track"><span/><span/><span/></div></div></section>

          <section className="panel"><div className="panel-head"><div><span className="section-index">02</span><div><h2>調查預算</h2><p>限制每個案件可使用的運算資源。</p></div></div></div><div className="budget-fields"><Field label="Max Agent Calls" value={draft.budgets.maxAgentCalls} onChange={(v) => update("budgets.maxAgentCalls", Number(v))}/><Field label="Max Tool Calls" value={draft.budgets.maxToolCalls} onChange={(v) => update("budgets.maxToolCalls", Number(v))}/><Field label="Max Steps" value={draft.budgets.maxSteps} onChange={(v) => update("budgets.maxSteps", Number(v))}/><Field label="Max Tokens" value={draft.budgets.maxTokens} step="1000" onChange={(v) => update("budgets.maxTokens", Number(v))}/><Field label="Max Cost USD" value={draft.budgets.maxCostUsd} step="0.1" suffix="USD" onChange={(v) => update("budgets.maxCostUsd", Number(v))}/></div></section>

          <section className="panel"><div className="panel-head"><div><span className="section-index">03</span><div><h2>停止條件</h2><p>滿足條件時提前結束調查，避免無效消耗。</p></div></div></div><div className="rules">{[["directEvidence", "直接證據", "取得可獨立支持判定的直接證據時停止。"], ["falsePositiveEvidence", "誤判證據", "取得足以確認為正常行為的反證時停止。"], ["diminishingReturns", "邊際效益遞減", "連續步驟未產生具影響力的新證據時停止。"]].map(([key, title, desc]) => <div className="rule" key={key}><div><strong>{title}</strong><span>{desc}</span></div><Switch label={title} checked={draft.stoppingRules[key as keyof typeof draft.stoppingRules]} onChange={(v) => update(`stoppingRules.${key}`, v)}/></div>)}</div></section>

          <section className="panel"><div className="panel-head"><div><span className="section-index">04</span><div><h2>Agent 設定</h2><p>設定代理元件的可用性、呼叫優先序與成本權重。</p></div></div></div><div className="table-wrap"><table><thead><tr><th>Agent</th><th>狀態</th><th>優先序</th><th>成本權重</th></tr></thead><tbody>{draft.agents.map((agent, index) => <tr key={agent.name}><td><div className="agent-name"><span>{agentLabels[agent.name].slice(0, 1)}</span><div><strong>{agentLabels[agent.name]}</strong><small>{agent.name}</small></div></div></td><td><div className="inline-switch"><Switch label={`啟用 ${agentLabels[agent.name]}`} checked={agent.enabled} onChange={(v) => updateAgent(index, "enabled", v)}/><span>{agent.enabled ? "啟用" : "停用"}</span></div></td><td><select aria-label={`${agentLabels[agent.name]} 優先序`} value={agent.priority} onChange={(e) => updateAgent(index, "priority", Number(e.target.value))}><option value="1">P1 · 最高</option><option value="2">P2 · 一般</option><option value="3">P3 · 次要</option></select></td><td><div className="weight"><input aria-label={`${agentLabels[agent.name]} 成本權重`} type="number" min="0" step="0.1" value={agent.costWeight} onChange={(e) => updateAgent(index, "costWeight", Number(e.target.value))}/><span>×</span></div></td></tr>)}</tbody></table></div></section>
        </div>

        <aside className="right-rail"><section className="panel runtime"><div className="rail-title"><Scale size={18}/><div><h2>近期調查用量</h2><p>CASE-2026-0912-0841</p></div><span className="live">調查中</span></div><div className="score"><span>Fraud Score</span><strong>0.91</strong><small>高於詐欺門檻 {draft.fraudThreshold.toFixed(2)}</small></div><BudgetBar label="Agent Calls" used={3} max={draft.budgets.maxAgentCalls}/><BudgetBar label="Tool Calls" used={9} max={draft.budgets.maxToolCalls}/><BudgetBar label="Steps" used={4} max={draft.budgets.maxSteps}/><BudgetBar label="Tokens" used={12430} max={draft.budgets.maxTokens}/><BudgetBar label="Cost" used={0.37} max={draft.budgets.maxCostUsd} unit="$"/><div className="runtime-foot"><span>Scoreboard Config <b>v{active.version}</b></span><span>Scoring Policy <b>{draft.scoringPolicyVersion}</b></span></div></section>
          <section className="panel history"><div className="rail-title"><Clock3 size={18}/><div><h2>版本紀錄</h2><p>最近 3 個版本</p></div></div>{data?.map((config, i) => <div className="history-item" key={config.id}><div className="timeline-mark">{config.status === "active" ? <Check size={13}/> : <span/>}</div><div><div><strong>v{config.version}</strong><span className={`status ${config.status}`}>{config.status === "active" ? "ACTIVE" : "RETIRED"}</span></div><p>{config.note}</p><small>{config.createdBy} · {new Date(config.createdAt).toLocaleDateString("zh-TW")}</small></div>{i === 0 && <ChevronRight size={16}/>}</div>)}<button className="history-link">查看完整版本紀錄 <ArrowRight size={15}/></button></section>
        </aside>
      </div>
      <div className="savebar"><div>{dirty ? <><AlertTriangle size={18}/><span><strong>設定已變更</strong>目前啟用的 v{active.version} 不受影響</span></> : <><Check size={18}/><span>目前沒有尚未儲存的變更</span></>}</div><div><button type="button" className="button secondary" disabled={!dirty} onClick={() => { setDraft(structuredClone(active)); setDirty(false); }}><RotateCcw size={16}/>放棄變更</button><button type="button" className="button primary" disabled={!dirty} onClick={() => setDialog(true)}><Save size={16}/>建立新版本</button></div></div>
    </form>

    {dialog && <div className="dialog-layer" role="presentation"><div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><button className="dialog-close icon-button" onClick={() => setDialog(false)} aria-label="關閉"><X size={20}/></button><div className="dialog-icon"><FilePlus2/></div><h2 id="dialog-title">建立 Scoreboard v{Math.max(...(data?.map((x) => x.version) ?? [0])) + 1}？</h2><p>此操作會建立新的草稿版本，不會直接啟用或覆寫現行生產設定。完成審核後才能進行啟用。</p><div className="dialog-summary"><span>來源版本 <b>v{active.version}</b></span><span>Scoring Policy <b>{draft.scoringPolicyVersion}</b></span><span>成本上限 <b>${draft.budgets.maxCostUsd.toFixed(2)}</b></span></div><div className="dialog-actions"><button className="button secondary" onClick={() => setDialog(false)}>取消</button><button className="button primary" onClick={submit} disabled={mutation.isPending}>{mutation.isPending && <LoaderCircle className="spin" size={16}/>}確認建立</button></div></div></div>}
    {toast && <div className="toast" role="status"><Check size={17}/>{toast}</div>}
  </AppContent>;
}

function AppContent({ children }: { children: React.ReactNode }) { return <>{children}</>; }
