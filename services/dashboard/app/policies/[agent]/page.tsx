import { AppShell } from "@/components/app-shell";
import { AgentPolicyEditor } from "@/features/policies/agent-policy-editor";
import { DetectionPolicyEditor } from "@/features/policies/detection-policy-editor";
import { PolicyEditorSwitch } from "@/features/policies/live-agent-policy-editor";
import { agentPolicyProfiles, getAgentPolicyProfile, getSubAgentProfiles } from "@/lib/api/agent-policies";
import { structuredPolicyConfigs } from "@/lib/api/structured-policies";
import { ArrowLeft, ArrowUpRight, Bot, Check, Database, FileCode2, GitBranch, LockKeyhole, RefreshCw, ShieldCheck, Wrench } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

export function generateStaticParams() {
  return agentPolicyProfiles.filter((profile) => !profile.parentAgent).map((profile) => ({ agent: profile.slug }));
}

export default async function AgentPolicyPage({ params }: { params: Promise<{ agent: string }> }) {
  const { agent } = await params;
  const profile = getAgentPolicyProfile(agent);
  if (!profile || profile.parentAgent) notFound();
  const subAgents = getSubAgentProfiles(profile.slug);
  const structuredPolicy = structuredPolicyConfigs[profile.slug];

  return <AppShell><div className="agent-policy-detail">
    <Link href="/policies" className="back-link"><ArrowLeft size={15}/>返回 Agent Policy</Link>
    <div className="agent-detail-head"><div className="agent-detail-title"><span className="agent-detail-icon"><Bot size={21}/></span><div><div className="agent-detail-kicker">AGENT POLICY · {profile.runtimeVersion}</div><h1>{profile.name}</h1></div></div><div className="agent-detail-actions"><span className={`agent-live-state ${profile.status}`}><i/>{profile.status === "active" ? "生效中" : "受限模式"}</span>{profile.workspaceLink && <Link href={profile.workspaceLink.href}>{profile.workspaceLink.label}<ArrowUpRight size={13}/></Link>}</div></div>
    <section className="panel agent-detail-meta"><div><span>Active Policy</span><strong>{profile.slug === "detection" ? "Live API" : profile.policies[0]?.version ?? "尚未發布"}</strong></div><div><span>Runtime</span><strong>{profile.runtimeVersion}</strong></div><div><span>Owner</span><strong>{profile.owner}</strong></div><div><span>最後發布</span><strong>{profile.slug === "detection" ? "由服務回報" : profile.updatedAt}</strong></div></section>

    <div className="agent-detail-grid"><div className="agent-detail-main">
      {subAgents.length > 0 && <section className="panel subagent-registry"><header><div><Bot size={18}/><div><span>DYNAMIC SUB-AGENT REGISTRY</span><h2>Investigation Sub-agents</h2></div></div><b>{subAgents.length} 個已註冊</b></header><div className="subagent-grid">{subAgents.map((subAgent) => <Link href={`/policies/${profile.slug}/${subAgent.slug}`} key={subAgent.slug}><div><span className={`implementation-state ${subAgent.implementationState ?? "implemented"}`}>{subAgent.implementationState === "placeholder" ? "尚未實作" : "可用"}</span><h3>{subAgent.name}</h3><p>{subAgent.role}</p></div><ArrowUpRight size={15}/></Link>)}</div></section>}

      {profile.slug === "detection" && <DetectionPolicyEditor/>}
      {structuredPolicy && (profile.slug === "patrol" || profile.slug === "association") && <PolicyEditorSwitch agent={profile.slug} demo={<AgentPolicyEditor config={structuredPolicy} toolCatalog={profile.toolConfiguration?.tools ?? []}/>}/>}

      <section className="panel applied-policy-panel"><header><div><ShieldCheck size={18}/><div><span>VERSIONED POLICY</span><h2>已發布版本</h2></div></div><b>{profile.policies.length} 個 Policy</b></header>{profile.policies.length > 0 ? <div>{profile.policies.map((policy) => <article key={`${policy.name}-${policy.version}`}><span className="policy-order">{String(profile.policies.indexOf(policy) + 1).padStart(2, "0")}</span><div><div><h3>{policy.name}</h3><code>{policy.version}</code></div><small>{policy.source}</small></div></article>)}</div> : <div className="empty-policy-state">尚未發布可用的 Agent Policy。</div>}</section>

      <details className="panel prompt-audit"><summary><div><FileCode2 size={18}/><div><span>READ-ONLY RUNTIME AUDIT</span><h2>Prompt 快照</h2></div></div><code>{profile.promptVersion}</code></summary>{profile.promptLayers && <div className="prompt-audit-layers"><header><GitBranch size={16}/><strong>Runtime 組合順序</strong></header><div className="prompt-layer-list">{profile.promptLayers.map((layer) => <article key={layer.order}><span>{String(layer.order).padStart(2, "0")}</span><div><div><h3>{layer.name}</h3><code>{layer.kind}</code></div><small>{layer.source} · {layer.version}</small></div></article>)}</div></div>}<pre>{profile.systemPrompt}</pre><footer><LockKeyhole size={14}/><span>唯讀；不可直接修改 system prompt。</span></footer></details>

      {profile.toolConfiguration && <details className="panel tool-evolution-audit"><summary><div><RefreshCw size={18}/><div><span>TOOL EVOLUTION AUDIT</span><h2>工具迭代與部署邊界</h2></div></div><small>展開檢視</small></summary><div className="tool-evolution-notes"><div><span>CURRENT</span><p>{profile.toolConfiguration.iteration.currentCapability}</p></div><div className="limitation"><span>ARCHITECTURE GAP</span><p>{profile.toolConfiguration.iteration.limitation}</p></div></div><ol>{profile.toolConfiguration.iteration.proposedFlow.map((stage, index) => <li key={stage}><span>{index + 1}</span><p>{stage}</p></li>)}</ol></details>}
    </div><aside className="agent-detail-side">
      {!structuredPolicy && <section className="panel capability-panel"><header><Wrench size={17}/><h2>允許工具</h2></header>{profile.tools.length > 0 ? profile.tools.map((tool) => <code key={tool}>{tool}</code>) : <p>目前 Registry 沒有可用工具。</p>}</section>}
      <section className="panel capability-panel"><header><Database size={17}/><h2>資料存取範圍</h2></header>{profile.dataAccess.map((access) => <p key={access}>{access}</p>)}</section>
      <section className="panel guardrail-panel"><header><LockKeyhole size={17}/><h2>不可由 Policy 覆寫</h2></header>{profile.guardrails.map((guardrail) => <div key={guardrail}><Check size={13}/><p>{guardrail}</p></div>)}</section>
    </aside></div>
  </div></AppShell>;
}
