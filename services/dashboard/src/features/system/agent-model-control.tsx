"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, Check, Cpu, LoaderCircle, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { systemControlApi, type AgentModelConfig } from "@/lib/api/system-control";

const labels: Record<AgentModelConfig["component"], string> = { detection: "Detection", investigation: "Investigation", patrol: "Patrol", association: "Association", "codex-builder": "Codex Builder" };

function ModelRow({ initial }: { initial: AgentModelConfig }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState(initial);
  useEffect(() => setDraft(initial), [initial]);
  const changed = draft.model !== initial.model || draft.reasoning_effort !== initial.reasoning_effort || draft.enabled !== initial.enabled;
  const mutation = useMutation({ mutationFn: systemControlApi.saveModel, onSuccess: async () => client.invalidateQueries({ queryKey: ["agent-models"] }) });
  return <article className="model-row">
    <div className="model-identity"><span><Bot size={18}/></span><div><strong>{labels[draft.component]}</strong><small>{draft.component}</small></div></div>
    <label><span>模型</span><select value={draft.model} onChange={(event) => setDraft({...draft, model: event.target.value})}>{draft.allowed_models.map((model) => <option key={model}>{model}</option>)}</select></label>
    <label><span>推理強度</span><select value={draft.reasoning_effort} onChange={(event) => setDraft({...draft, reasoning_effort: event.target.value as AgentModelConfig["reasoning_effort"]})}><option value="none">None</option><option value="minimal">Minimal</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">XHigh</option></select></label>
    <label className="model-enabled"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({...draft, enabled: event.target.checked})}/><span>啟用模型</span></label>
    <button type="button" className="model-save" disabled={!changed || mutation.isPending} onClick={() => mutation.mutate(draft)}>{mutation.isPending ? <LoaderCircle className="spin" size={16}/> : mutation.isSuccess && !changed ? <Check size={16}/> : <Save size={16}/>}<span>{mutation.isPending ? "儲存中" : "儲存"}</span></button>
    <div className="model-feedback" aria-live="polite">{mutation.isError ? `儲存失敗：${mutation.error.message}` : mutation.isSuccess && !changed ? "已套用至後續新任務" : ""}</div>
  </article>;
}

export function AgentModelControl() {
  const query = useQuery({ queryKey: ["agent-models"], queryFn: systemControlApi.models });
  return <section className="panel model-control"><header><div className="model-heading"><Cpu size={18}/><div><span>RUNTIME CONTROL</span><h2>Agent 模型</h2><p>設定會套用至後續建立的新任務；執行中的任務不會被更改。</p></div></div></header>
    {query.isLoading && <div className="model-state" aria-live="polite"><LoaderCircle className="spin"/>載入模型設定…</div>}
    {query.isError && <div className="model-state error" role="alert"><AlertTriangle/><div><strong>無法載入模型設定</strong><span>{query.error.message}</span></div><button onClick={() => query.refetch()}>重試</button></div>}
    {query.data && <div className="model-list">{query.data.map((config) => <ModelRow key={config.component} initial={config}/>)}</div>}
    <footer><strong>Deterministic components</strong><span>Evolution、Evaluator、Governance 目前不直接呼叫模型。</span></footer>
  </section>;
}
