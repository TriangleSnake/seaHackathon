import { AppShell } from "@/components/app-shell";
import { agentPolicyProfiles } from "@/lib/api/agent-policies";
import { ArrowRight, Bot, BookOpenCheck } from "lucide-react";
import Link from "next/link";

export default function PoliciesPage() {
  const topLevelAgents = agentPolicyProfiles.filter((profile) => !profile.parentAgent);
  const subAgentCount = agentPolicyProfiles.length - topLevelAgents.length;
  const policyCount = new Set(agentPolicyProfiles.flatMap((profile) => profile.policies.map((policy) => `${policy.name}:${policy.version}`))).size;
  return <AppShell>
    <div className="page-head"><div><div className="breadcrumb">Control Plane / Agent Policy</div><h1>Agent Policy</h1></div></div>
    <section className="agent-policy-summary">
      <div><Bot/><span>頂層 Agent</span><strong>{topLevelAgents.length}</strong><small>目前 Runtime Registry</small></div>
      <div><Bot/><span>Investigation Sub-agents</span><strong>{subAgentCount}</strong><small>成員可隨版本替換</small></div>
      <div><BookOpenCheck/><span>已發布 Policy</span><strong>{policyCount}</strong><small>不可變更版本</small></div>
    </section>
    <section className="panel agent-registry">
      <header><div><span>TOP-LEVEL AGENT REGISTRY</span><h2>選擇 Agent</h2></div><span className="registry-state"><i/>Registry synced</span></header>
      <div className="agent-policy-grid">{topLevelAgents.map((profile) => {
        const childCount = agentPolicyProfiles.filter((candidate) => candidate.parentAgent === profile.slug).length;
        return <Link href={`/policies/${profile.slug}`} key={profile.slug} className="agent-policy-card">
        <div className="agent-card-top"><span className="agent-card-icon"><Bot size={17}/></span><span className={`agent-live-state ${profile.status}`}><i/>{profile.status === "active" ? "生效中" : "受限模式"}</span></div>
        <h2>{profile.name}</h2><strong>{profile.role}</strong>
        <div className="agent-card-tags">{childCount > 0 && <span className="subagent-count">{childCount} SUB-AGENTS</span>}{profile.policies.slice(0, 2).map((policy) => <span key={`${policy.name}-${policy.version}`}>{policy.name} {policy.version}</span>)}{profile.policies.length > 2 && <span>+{profile.policies.length - 2}</span>}</div>
        <footer><code>{profile.policies[0]?.version ?? "尚未發布"}</code><span>管理 Policy <ArrowRight size={14}/></span></footer>
      </Link>;})}</div>
    </section>
  </AppShell>;
}
