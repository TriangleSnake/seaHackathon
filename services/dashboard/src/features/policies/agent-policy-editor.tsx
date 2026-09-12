"use client";

import type { AgentToolGrant } from "@/types/agent-policy";
import type { PolicyNumberField, StructuredPolicyConfig, StructuredPolicyVariant } from "@/types/structured-policy";
import { ArrowDown, ArrowUp, Check, CircleAlert, FlaskConical, GitCompareArrows, Plus, Save, Send, ShieldCheck, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

type Props = {
  config: StructuredPolicyConfig;
  toolCatalog: AgentToolGrant[];
};

function cloneVariant(variant: StructuredPolicyVariant): StructuredPolicyVariant {
  return JSON.parse(JSON.stringify(variant)) as StructuredPolicyVariant;
}

function BoundedNumber({ field, onChange }: { field: PolicyNumberField; onChange: (value: number) => void }) {
  return <label className="policy-number-field">
    <span>{field.label}</span>
    <div><input type="number" min={field.min} max={field.max} value={field.value} onChange={(event) => onChange(Math.min(field.max, Math.max(field.min, Number(event.target.value))))}/>{field.suffix && <small>{field.suffix}</small>}</div>
    <small>{field.min}–{field.max}</small>
  </label>;
}

export function AgentPolicyEditor({ config, toolCatalog }: Props) {
  const [selected, setSelected] = useState(config.variants[0].id);
  const [drafts, setDrafts] = useState<Record<string, StructuredPolicyVariant>>(() => Object.fromEntries(config.variants.map((variant) => [variant.id, cloneVariant(variant)])));
  const [notice, setNotice] = useState("編輯不會影響目前的 Active Policy。");
  const draft = drafts[selected];
  const original = config.variants.find((variant) => variant.id === selected) ?? config.variants[0];
  const changed = useMemo(() => JSON.stringify(draft) !== JSON.stringify(original), [draft, original]);

  function update(patch: Partial<StructuredPolicyVariant>) {
    setDrafts((current) => ({ ...current, [selected]: { ...current[selected], ...patch } }));
  }

  function updateNumber(group: "search" | "budget", key: string, value: number) {
    update({ [group]: (draft[group] ?? []).map((field) => field.key === key ? { ...field, value } : field) });
  }

  function moveText(group: "guidance" | "stoppingConditions", index: number, direction: -1 | 1) {
    const items = [...(draft[group] ?? [])];
    const target = index + direction;
    if (target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
    update({ [group]: items });
  }

  function updateText(group: "guidance" | "stoppingConditions", index: number, value: string) {
    update({ [group]: (draft[group] ?? []).map((item, itemIndex) => itemIndex === index ? value : item) });
  }

  function removeText(group: "guidance" | "stoppingConditions", index: number) {
    update({ [group]: (draft[group] ?? []).filter((_, itemIndex) => itemIndex !== index) });
  }

  function addText(group: "guidance" | "stoppingConditions") {
    update({ [group]: [...(draft[group] ?? []), ""] });
  }

  function saveLocalDraft() {
    const hasInvalidNumber = [...(draft.search ?? []), ...draft.budget].some((field) => field.value < field.min || field.value > field.max);
    if (!draft.objective.trim() || draft.allowedTools.length === 0 || draft.stoppingConditions.some((item) => !item.trim()) || hasInvalidNumber) {
      setNotice("草稿未通過前端檢查：請確認 Objective、工具、數值範圍與停止條件。");
      return;
    }
    setNotice("草稿僅保留於本次瀏覽工作階段。");
  }

  return <section className="panel structured-policy-editor">
    <header className="policy-editor-head">
      <div><ShieldCheck size={18}/><div><span>STRUCTURED AGENT POLICY</span><h2>Policy 控制</h2></div></div>
      <div className="policy-version-state"><span>ACTIVE</span><strong>{draft.version}</strong><small>來源 · human</small></div>
    </header>

    <div className="policy-strategy-tabs" role="tablist" aria-label="Policy strategy">
      {config.variants.map((variant) => <button type="button" role="tab" aria-selected={selected === variant.id} className={selected === variant.id ? "active" : ""} key={variant.id} onClick={() => { setSelected(variant.id); setNotice("編輯不會影響目前的 Active Policy。"); }}><span>{variant.label}</span></button>)}
    </div>

    <div className="policy-editor-context"><div><span>POLICY ID</span><code>{draft.policyId}</code></div><div><span>SOURCE</span><code>{draft.source}</code></div><div><span>DRAFT STATUS</span><strong className={changed ? "changed" : "clean"}>{changed ? "UNSAVED CHANGES" : "MATCHES ACTIVE"}</strong></div></div>

    <div className="policy-editor-body">
      <section className="policy-field-section policy-objective"><div className="section-label"><span>01</span><div><h3>Objective</h3></div></div><textarea value={draft.objective} rows={4} onChange={(event) => update({ objective: event.target.value })}/></section>

      {draft.relationGuidance && <section className="policy-field-section"><div className="section-label"><span>02</span><div><h3>Relation guidance</h3></div></div><div className="relation-policy-table"><table><thead><tr><th>Enabled</th><th>Relation type</th><th>Base weight</th><th>需第二訊號</th></tr></thead><tbody>{draft.relationGuidance.map((rule, index) => <tr key={rule.type}><td><input aria-label={`啟用 ${rule.type}`} type="checkbox" checked={rule.enabled} onChange={(event) => update({ relationGuidance: draft.relationGuidance?.map((item, itemIndex) => itemIndex === index ? { ...item, enabled: event.target.checked } : item) })}/></td><td><code>{rule.type}</code></td><td><input aria-label={`${rule.type} 權重`} type="number" min="0" max="1" step="0.05" value={rule.baseWeight} onChange={(event) => update({ relationGuidance: draft.relationGuidance?.map((item, itemIndex) => itemIndex === index ? { ...item, baseWeight: Math.min(1, Math.max(0, Number(event.target.value))) } : item) })}/></td><td><label className="compact-switch"><input type="checkbox" checked={rule.requiresCorroboration} onChange={(event) => update({ relationGuidance: draft.relationGuidance?.map((item, itemIndex) => itemIndex === index ? { ...item, requiresCorroboration: event.target.checked } : item) })}/><span>{rule.requiresCorroboration ? "Required" : "Not required"}</span></label></td></tr>)}</tbody></table></div></section>}

      {draft.guidance && <section className="policy-field-section"><div className="section-label"><span>02</span><div><h3>Exploration guidance</h3></div></div><div className="ordered-policy-list">{draft.guidance.map((item, index) => <div key={index}><span>{String(index + 1).padStart(2, "0")}</span><input value={item} aria-label={`Guidance ${index + 1}`} onChange={(event) => updateText("guidance", index, event.target.value)}/><div><button type="button" aria-label="上移" onClick={() => moveText("guidance", index, -1)} disabled={index === 0}><ArrowUp size={13}/></button><button type="button" aria-label="下移" onClick={() => moveText("guidance", index, 1)} disabled={index === draft.guidance!.length - 1}><ArrowDown size={13}/></button><button type="button" aria-label="刪除" onClick={() => removeText("guidance", index)}><Trash2 size={13}/></button></div></div>)}<button type="button" className="add-policy-row" onClick={() => addText("guidance")}><Plus size={13}/>新增 guidance</button></div></section>}

      <section className="policy-field-section"><div className="section-label"><span>03</span><div><h3>Search & budget</h3></div></div><div className="policy-number-grid">{draft.search?.map((field) => <BoundedNumber key={field.key} field={field} onChange={(value) => updateNumber("search", field.key, value)}/>)}{draft.budget.map((field) => <BoundedNumber key={field.key} field={field} onChange={(value) => updateNumber("budget", field.key, value)}/>)}{draft.evidenceRequirements && <><BoundedNumber field={{ key: "minimumEvidenceRefs", label: "Minimum evidence", value: draft.evidenceRequirements.minimumEvidenceRefs, min: 1, max: 20 }} onChange={(value) => update({ evidenceRequirements: { ...draft.evidenceRequirements!, minimumEvidenceRefs: value } })}/><BoundedNumber field={{ key: "preferIndependentSignals", label: "Independent signals", value: draft.evidenceRequirements.preferIndependentSignals, min: 1, max: 10 }} onChange={(value) => update({ evidenceRequirements: { ...draft.evidenceRequirements!, preferIndependentSignals: value } })}/><label className="policy-toggle-field"><span>Skip duplicate cases</span><input type="checkbox" checked={draft.evidenceRequirements.skipDuplicateOpenCases} onChange={(event) => update({ evidenceRequirements: { ...draft.evidenceRequirements!, skipDuplicateOpenCases: event.target.checked } })}/></label></>}</div></section>

      <section className="policy-field-section"><div className="section-label"><span>04</span><div><h3>Allowed tools</h3></div></div><div className="policy-tool-grid">{toolCatalog.map((tool) => { const enabled = draft.allowedTools.includes(tool.name); return <label key={tool.name} className={enabled ? "enabled" : ""}><input type="checkbox" checked={enabled} onChange={(event) => update({ allowedTools: event.target.checked ? [...draft.allowedTools, tool.name] : draft.allowedTools.filter((name) => name !== tool.name) })}/><span><code>{tool.name}</code></span><Check size={13}/></label>; })}</div></section>

      <section className="policy-field-section"><div className="section-label"><span>05</span><div><h3>Stopping conditions</h3></div></div><div className="ordered-policy-list">{draft.stoppingConditions.map((item, index) => <div key={index}><span>{String(index + 1).padStart(2, "0")}</span><input value={item} aria-label={`Stopping condition ${index + 1}`} onChange={(event) => updateText("stoppingConditions", index, event.target.value)}/><div><button type="button" aria-label="上移" onClick={() => moveText("stoppingConditions", index, -1)} disabled={index === 0}><ArrowUp size={13}/></button><button type="button" aria-label="下移" onClick={() => moveText("stoppingConditions", index, 1)} disabled={index === draft.stoppingConditions.length - 1}><ArrowDown size={13}/></button><button type="button" aria-label="刪除" onClick={() => removeText("stoppingConditions", index)}><Trash2 size={13}/></button></div></div>)}<button type="button" className="add-policy-row" onClick={() => addText("stoppingConditions")}><Plus size={13}/>新增停止條件</button></div></section>
    </div>

    <div className="policy-workflow"><div className="workflow-step active"><span>1</span><div><strong>Draft</strong><small>不影響 Agent</small></div></div><div className="workflow-line"/><div className="workflow-step"><span>2</span><div><strong>Validate & Test</strong><small>不 handoff</small></div></div><div className="workflow-line"/><div className="workflow-step"><span>3</span><div><strong>Publish</strong><small>建立 immutable version</small></div></div></div>
    <footer className="policy-action-bar"><div className="policy-notice"><CircleAlert size={14}/><span>{notice}</span></div><div><button type="button" className="secondary" onClick={() => { setDrafts((current) => ({ ...current, [selected]: cloneVariant(original) })); setNotice("已還原為目前 active version。"); }} disabled={!changed}><GitCompareArrows size={14}/>還原變更</button><button type="button" className="secondary" onClick={saveLocalDraft}><Save size={14}/>Save draft</button><button type="button" disabled title="等待 POST /policies/{agent}/{strategy}/test"><FlaskConical size={14}/>Test policy</button><button type="button" disabled title="等待 POST /policies/{agent}/{strategy}/publish"><Send size={14}/>Publish</button></div></footer>
  </section>;
}
