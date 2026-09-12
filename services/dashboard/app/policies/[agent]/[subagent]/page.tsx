import { AppShell } from "@/components/app-shell";
import { agentPolicyProfiles, getAgentPolicyProfile, getSubAgentProfile, getSubAgentProfiles } from "@/lib/api/agent-policies";
import { ArrowLeft, Bot, FileCode2, LockKeyhole, Wrench } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

export function generateStaticParams() {
  return agentPolicyProfiles.flatMap((profile) => getSubAgentProfiles(profile.slug).map((subAgent) => ({ agent: profile.slug, subagent: subAgent.slug })));
}

export default async function SubAgentPolicyPage({ params }: { params: Promise<{ agent: string; subagent: string }> }) {
  const { agent, subagent } = await params;
  const parent = getAgentPolicyProfile(agent);
  const profile = getSubAgentProfile(agent, subagent);
  if (!parent || !profile) notFound();

  return <AppShell><div className="agent-policy-detail subagent-detail">
    <Link href={`/policies/${parent.slug}`} className="back-link"><ArrowLeft size={15}/>返回 {parent.name}</Link>
    <div className="agent-detail-head"><div className="agent-detail-title"><span className="agent-detail-icon"><Bot size={21}/></span><div><div className="agent-detail-kicker">SUB-AGENT · PARENT {parent.name.toUpperCase()}</div><h1>{profile.name}</h1></div></div><span className={`implementation-state ${profile.implementationState ?? "implemented"}`}>{profile.implementationState === "placeholder" ? "尚未實作" : "可用"}</span></div>
    <section className="panel agent-detail-meta"><div><span>Parent Agent</span><strong>{parent.name}</strong></div><div><span>Prompt Version</span><strong>{profile.promptVersion}</strong></div><div><span>Runtime</span><strong>{profile.runtimeVersion}</strong></div><div><span>Source</span><strong>{profile.sourceRef ?? "Registry"}</strong></div></section>
    <div className="agent-detail-grid"><div className="agent-detail-main">
      <section className="panel prompt-panel"><header><div><FileCode2 size={18}/><div><span>SUB-AGENT PROMPT</span><h2>目前 Prompt 狀態</h2></div></div><code>{profile.promptVersion}</code></header><pre>{profile.systemPrompt}</pre><footer><LockKeyhole size={14}/><span>Sub-agent 成員與 Prompt 均由 Investigation Registry 版本管理。</span></footer></section>
    </div><aside className="agent-detail-side">
      <section className="panel capability-panel"><header><Wrench size={17}/><h2>允許工具</h2></header>{profile.tools.length ? profile.tools.map((tool) => <code key={tool}>{tool}</code>) : <p>目前尚未註冊工具。</p>}</section>
      <section className="panel guardrail-panel"><header><LockKeyhole size={17}/><h2>執行邊界</h2></header>{profile.guardrails.map((guardrail) => <div key={guardrail}><p>{guardrail}</p></div>)}</section>
    </aside></div>
  </div></AppShell>;
}
