"use client";

import { detectionApi } from "@/lib/api/detection";
import type { DetectionPolicy, DetectionPolicyVersion, DetectionResult, DetectorType } from "@/types/detection";
import { useQuery } from "@tanstack/react-query";
import { Activity, Check, CircleAlert, FlaskConical, LoaderCircle, RefreshCw, RotateCcw, Save, Send, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const detectorLabels: Record<DetectorType, string> = {
  rule_based: "Rule based",
  anomaly: "Anomaly",
  llm_classifier: "LLM classifier",
  ml_classifier: "ML classifier",
};

const numberFields: Array<{ group: "anomaly" | "rule_based" | "llm_classifier"; key: string; label: string; min: number; max: number; step?: number }> = [
  { group: "anomaly", key: "messages_per_hour", label: "每小時訊息", min: 1, max: 1000 },
  { group: "anomaly", key: "listings_per_hour", label: "每小時刊登", min: 1, max: 1000 },
  { group: "anomaly", key: "disputes_per_week", label: "每週爭議", min: 1, max: 100 },
  { group: "anomaly", key: "payment_instruments_per_hour", label: "每小時付款工具", min: 2, max: 100 },
  { group: "anomaly", key: "login_countries_per_day", label: "每日登入國家", min: 2, max: 100 },
  { group: "anomaly", key: "login_devices_per_day", label: "每日登入裝置", min: 2, max: 100 },
  { group: "rule_based", key: "access_window_minutes", label: "存取觀察窗", min: 1, max: 10080 },
  { group: "rule_based", key: "reused_image_min_products", label: "重複圖片商品數", min: 2, max: 100 },
  { group: "llm_classifier", key: "confidence_threshold", label: "LLM 信心門檻", min: .5, max: 1, step: .01 },
];

const listFields: Array<{ key: keyof DetectionPolicy["rule_based"]; label: string }> = [
  { key: "active_report_statuses", label: "有效檢舉狀態" },
  { key: "chat_request_phrases", label: "對話觸發詞" },
  { key: "chat_negations", label: "否定語句" },
  { key: "risk_domain_suffixes", label: "風險網域後綴" },
  { key: "sensitive_security_events", label: "敏感安全事件" },
  { key: "delivery_claim_terms", label: "履約爭議詞" },
];

function clone(policy: DetectionPolicy) { return structuredClone(policy); }

export function DetectionPolicyEditor() {
  const query = useQuery({ queryKey: ["detection-policies"], queryFn: detectionApi.listPolicies, retry: false });
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState<DetectionPolicy | null>(null);
  const [notice, setNotice] = useState("從 Detection 服務讀取 Policy。編輯不會改動 Active version。");
  const [busy, setBusy] = useState("");
  const [subjectType, setSubjectType] = useState<"account" | "shop" | "product" | "order" | "transaction" | "message">("message");
  const [subjectId, setSubjectId] = useState("MSG-0901");
  const [testResult, setTestResult] = useState<DetectionResult | null>(null);

  useEffect(() => {
    const versions = query.data;
    if (!versions?.length || selected) return;
    const initial = versions.find((item) => item.active) ?? versions[0];
    setSelected(initial.version);
    setDraft(clone(initial.document));
  }, [query.data, selected]);

  const selectedVersion = useMemo(() => query.data?.find((item) => item.version === selected), [query.data, selected]);
  const changed = Boolean(draft && selectedVersion && JSON.stringify(draft) !== JSON.stringify(selectedVersion.document));

  function choose(item: DetectionPolicyVersion) {
    setSelected(item.version);
    setDraft(clone(item.document));
    setTestResult(null);
    setNotice(item.active ? "這是目前 Active version；若修改內容，請使用新的版本名稱。" : "已載入此版本，不影響目前 Active version。");
  }

  function patch(updater: (current: DetectionPolicy) => DetectionPolicy) {
    setDraft((current) => current ? updater(clone(current)) : current);
  }

  async function run(name: string, action: () => Promise<string>) {
    setBusy(name);
    try { setNotice(await action()); await query.refetch(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "操作失敗，請稍後重試。"); }
    finally { setBusy(""); }
  }

  if (query.isLoading) return <section className="panel detection-policy-shell detection-policy-loading"><LoaderCircle className="spin"/><span>正在讀取 Detection Policy…</span></section>;
  if (query.isError) return <section className="panel detection-policy-shell detection-policy-offline"><CircleAlert/><div><h2>Detection 尚未連線</h2><p>{query.error instanceof Error ? query.error.message : "無法讀取服務"}</p><button onClick={() => query.refetch()}><RefreshCw size={15}/>重新連線</button></div></section>;
  if (!draft || !query.data?.length) return <section className="panel detection-policy-shell detection-policy-offline"><CircleAlert/><div><h2>尚無 Detection Policy</h2><p>服務已連線，但目前沒有可編輯的版本。</p></div></section>;

  return <section className="panel detection-policy-shell">
    <header className="detection-policy-head"><div><ShieldCheck size={18}/><div><span>LIVE DETECTION POLICY</span><h2>Detection Components</h2></div></div><div className="detection-policy-active"><i/><span>ACTIVE</span><strong>{query.data.find((item) => item.active)?.version ?? "未指定"}</strong></div></header>

    <nav className="detection-version-tabs" aria-label="Detection Policy versions">{query.data.map((item) => <button key={item.version} className={selected === item.version ? "selected" : ""} onClick={() => choose(item)}><span>{item.version}</span>{item.active && <b>ACTIVE</b>}<small>{item.source}</small></button>)}</nav>

    <div className="detection-policy-body">
      <section className="detection-policy-section"><div className="detection-section-title"><span>01</span><div><h3>版本與預設檢查</h3><p>Policy 依版本選擇 detector，不把執行順序寫死。</p></div></div><div className="detection-policy-basics"><label><span>Version</span><input value={draft.version} onChange={(event) => patch((value) => ({ ...value, version: event.target.value }))}/></label><fieldset><legend>Default checks</legend>{(Object.keys(detectorLabels) as DetectorType[]).map((type) => <label key={type}><input type="checkbox" checked={draft.default_checks.includes(type)} onChange={(event) => patch((value) => ({ ...value, default_checks: event.target.checked ? [...value.default_checks, type] : value.default_checks.filter((item) => item !== type) }))}/><span>{detectorLabels[type]}</span></label>)}</fieldset></div></section>

      <section className="detection-policy-section"><div className="detection-section-title"><span>02</span><div><h3>Component registry</h3><p>每個 component 可獨立換版本、停用或指定失敗策略。</p></div></div><div className="detection-component-list">{draft.components.map((component, index) => <article key={`${component.id}-${index}`} className={component.enabled ? "enabled" : ""}><label className="detection-component-toggle"><input type="checkbox" checked={component.enabled} aria-label={`啟用 ${component.id}`} onChange={(event) => patch((value) => { value.components[index].enabled = event.target.checked; return value; })}/><span/></label><div><strong>{component.id}</strong><small>{detectorLabels[component.type]}</small></div><label><span>Version</span><input value={component.version} onChange={(event) => patch((value) => { value.components[index].version = event.target.value; return value; })}/></label><label><span>Failure mode</span><select value={component.failure_mode} onChange={(event) => patch((value) => { value.components[index].failure_mode = event.target.value as "continue" | "fail"; return value; })}><option value="continue">Continue</option><option value="fail">Fail request</option></select></label></article>)}</div></section>

      <section className="detection-policy-section"><div className="detection-section-title"><span>03</span><div><h3>偵測門檻</h3><p>門檻屬於所選 Policy，發布後版本內容不可變更。</p></div></div><div className="detection-threshold-grid">{numberFields.map((field) => { const group = draft[field.group] as unknown as Record<string, number>; return <label key={`${field.group}-${field.key}`}><span>{field.label}</span><input type="number" min={field.min} max={field.max} step={field.step ?? 1} value={group[field.key]} onChange={(event) => patch((value) => { const target = value[field.group] as unknown as Record<string, number>; target[field.key] = Number(event.target.value); return value; })}/><small>{field.min}–{field.max}</small></label>; })}</div></section>

      <details className="detection-rule-details"><summary>規則詞庫與事件集合 <span>{listFields.reduce((sum, field) => sum + (draft.rule_based[field.key] as string[]).length, 0)} items</span></summary><div>{listFields.map((field) => <label key={field.key}><span>{field.label}</span><textarea rows={4} value={(draft.rule_based[field.key] as string[]).join("\n")} onChange={(event) => patch((value) => { (value.rule_based[field.key] as string[]) = event.target.value.split("\n").map((item) => item.trim()).filter(Boolean); return value; })}/></label>)}</div></details>

      <section className="detection-test-panel"><div className="detection-section-title"><span>04</span><div><h3>用目前草稿測試</h3><p>不發布、不切換 Active version，直接回傳每個 component 的執行結果。</p></div></div><div className="detection-test-form"><label><span>Subject type</span><select value={subjectType} onChange={(event) => setSubjectType(event.target.value as typeof subjectType)}>{["account","shop","product","order","transaction","message"].map((type) => <option key={type}>{type}</option>)}</select></label><label><span>Subject ID</span><input value={subjectId} onChange={(event) => setSubjectId(event.target.value)}/></label><button disabled={!subjectId || Boolean(busy)} onClick={() => run("test", async () => { const result = await detectionApi.testPolicy(draft, { subject: { type: subjectType, id: subjectId }, trigger_context: { source: "api", reason: "dashboard-policy-test" } }); setTestResult(result); return `測試完成：${result.component_results.length} 個 components，${result.triggers.length} 個 triggers。`; })}>{busy === "test" ? <LoaderCircle className="spin" size={15}/> : <FlaskConical size={15}/>}Test draft</button></div>{testResult && <div className="detection-test-result"><header><div><Activity size={16}/><strong>{testResult.detection_id}</strong></div><span className={testResult.detected ? "detected" : "clear"}>{testResult.detected ? "DETECTED" : "NO SIGNAL"}</span></header><div>{testResult.component_results.map((result) => <article key={result.component_id}><i className={result.status}/><div><strong>{result.component_id}</strong><small>{result.detector} · {result.version}</small></div><span>{result.status}</span><b>{result.latency_ms.toFixed(1)} ms</b><em>{result.trigger_count} triggers</em></article>)}</div></div>}</section>
    </div>

    <footer className="detection-policy-actions"><div role="status" aria-live="polite"><CircleAlert size={14}/><span>{notice}</span></div><div><button className="secondary" disabled={!changed || Boolean(busy)} onClick={() => selectedVersion && setDraft(clone(selectedVersion.document))}><RefreshCw size={14}/>還原</button><button className="secondary" disabled={!selectedVersion || selectedVersion.active || Boolean(busy)} onClick={() => { if (selectedVersion && window.confirm(`確定將 Active version 切回 ${selectedVersion.version}？`)) void run("rollback", async () => { await detectionApi.rollbackPolicy(selectedVersion.version); return `Active version 已切換為 ${selectedVersion.version}。`; }); }}><RotateCcw size={14}/>Rollback</button><button disabled={Boolean(busy)} onClick={() => run("validate", async () => { await detectionApi.validatePolicy(draft); return `Policy ${draft.version} 通過 schema 驗證。`; })}><Check size={14}/>Validate</button><button disabled={Boolean(busy)} onClick={() => run("save", async () => { await detectionApi.saveDraft(draft); return `已建立草稿 ${draft.version}。`; })}><Save size={14}/>Save draft</button><button className="publish" disabled={Boolean(busy)} onClick={() => { if (window.confirm(`確定發布 ${draft.version} 並設為 Active？`)) void run("publish", async () => { await detectionApi.publishPolicy(draft); return `已發布並啟用 ${draft.version}。`; }); }}><Send size={14}/>Publish</button></div></footer>
  </section>;
}
