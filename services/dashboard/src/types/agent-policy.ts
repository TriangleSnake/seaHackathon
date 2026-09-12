export interface AppliedAgentPolicy {
  name: string;
  version: string;
  source: string;
  scope: string;
}

export interface AgentPolicyProfile {
  slug: string;
  name: string;
  role: string;
  summary?: string;
  status: "active" | "limited";
  promptVersion: string;
  runtimeVersion: string;
  owner: string;
  updatedAt: string;
  systemPrompt: string;
  policies: AppliedAgentPolicy[];
  tools: string[];
  dataAccess: string[];
  guardrails: string[];
  inputContract: string[];
  outputContract: string[];
  promptLayers?: AgentPromptLayer[];
  runtimeVariants?: AgentRuntimeVariant[];
  toolConfiguration?: AgentToolConfiguration;
  workspaceLink?: { href: string; label: string };
  parentAgent?: string;
  implementationState?: "implemented" | "placeholder";
  sourceRef?: string;
}

export interface AgentPromptLayer {
  order: number;
  name: string;
  kind: "system" | "strategy" | "policy" | "run-input";
  source: string;
  version: string;
  description: string;
}

export interface AgentRuntimeVariant {
  id: string;
  label: string;
  policyId: string;
  policyVersion: string;
  promptSource: string;
  description: string;
  limits: Array<{ label: string; value: string | number }>;
  allowedTools: string[];
}

export interface AgentToolGrant {
  name: string;
  description: string;
  source: string;
  access: "read-only" | "write";
  allowedIn: string[];
}

export interface AgentToolConfiguration {
  gateway: string;
  gatewayVersion: string;
  registrySource: string;
  filterMode: string;
  cacheMode: string;
  tools: AgentToolGrant[];
  iteration: {
    currentCapability: string;
    limitation: string;
    proposedFlow: string[];
  };
}
