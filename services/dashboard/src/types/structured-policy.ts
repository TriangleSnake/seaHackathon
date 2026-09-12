export interface PolicyNumberField {
  key: string;
  label: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
}

export interface RelationGuidanceRule {
  type: string;
  baseWeight: number;
  requiresCorroboration: boolean;
  enabled: boolean;
}

export interface PolicyEvidenceRequirements {
  minimumEvidenceRefs: number;
  preferIndependentSignals: number;
  skipDuplicateOpenCases: boolean;
  knownPatterns: string[];
}

export interface StructuredPolicyVariant {
  id: string;
  label: string;
  description: string;
  policyId: string;
  version: string;
  objective: string;
  allowedTools: string[];
  guidance?: string[];
  evidenceRequirements?: PolicyEvidenceRequirements;
  relationGuidance?: RelationGuidanceRule[];
  search?: PolicyNumberField[];
  budget: PolicyNumberField[];
  stoppingConditions: string[];
  source: string;
}

export interface StructuredPolicyConfig {
  agentSlug: string;
  variants: StructuredPolicyVariant[];
}
