import type { StructuredPolicyConfig } from "@/types/structured-policy";

export const structuredPolicyConfigs: Record<string, StructuredPolicyConfig> = {
  patrol: {
    agentSlug: "patrol",
    variants: [
      {
        id: "exploit",
        label: "Exploit",
        description: "套用已核准模式，優先尋找高精準度且證據完整的調查候選。",
        policyId: "patrol-exploit",
        version: "0.1.0",
        objective: "Apply approved fraud patterns to find more evidence-backed investigation candidates with high precision.",
        allowedTools: ["get_patrol_overview", "search_accounts", "get_account_activity", "find_high_density_ips", "find_new_account_bursts", "find_shared_ip_accounts", "find_shared_device_accounts", "get_entity_neighbors", "get_previous_cases", "get_evidence_records"],
        guidance: ["Evaluate approved patterns against recent observations.", "Require corroboration when an indicator has common benign explanations.", "Prefer precision, recency, and impact over broad coverage."],
        evidenceRequirements: { minimumEvidenceRefs: 1, preferIndependentSignals: 2, skipDuplicateOpenCases: true, knownPatterns: [] },
        budget: [
          { key: "max_turns", label: "Max turns", value: 12, min: 1, max: 50 },
          { key: "max_discoveries", label: "Max discoveries", value: 5, min: 0, max: 100 },
        ],
        stoppingConditions: ["No approved pattern has another evidence-backed match.", "The maximum turn budget is reached.", "The maximum discovery count is reached."],
        source: "services/patrol/policies/exploit.json",
      },
      {
        id: "explore",
        label: "Explore",
        description: "以有界抽樣與可反駁假說，尋找尚未被既有模式涵蓋的異常。",
        policyId: "patrol-explore",
        version: "0.1.0",
        objective: "Discover evidence-backed anomalies and hypotheses that are not adequately covered by approved fraud patterns.",
        allowedTools: ["get_patrol_overview", "sample_accounts", "search_accounts", "get_account_activity", "find_high_density_ips", "find_new_account_bursts", "find_shared_ip_accounts", "find_shared_device_accounts", "get_entity_neighbors", "get_previous_cases", "get_evidence_records"],
        guidance: ["Start with a bounded random sample instead of only top-risk subjects.", "Generate falsifiable hypotheses, test them, and actively seek counterexamples.", "Vary populations and time windows across runs to improve discovery coverage."],
        evidenceRequirements: { minimumEvidenceRefs: 1, preferIndependentSignals: 2, skipDuplicateOpenCases: true, knownPatterns: [] },
        budget: [
          { key: "max_turns", label: "Max turns", value: 16, min: 1, max: 50 },
          { key: "max_discoveries", label: "Max discoveries", value: 3, min: 0, max: 100 },
        ],
        stoppingConditions: ["No sampled anomaly supports an evidence-backed lead.", "The maximum turn budget is reached.", "The maximum discovery count is reached."],
        source: "services/patrol/policies/explore.json",
      },
    ],
  },
  association: {
    agentSlug: "association",
    variants: [
      {
        id: "focused",
        label: "Focused",
        description: "從指定 subject 尋找少量、高可信度且具證據的直接關聯。",
        policyId: "association-focused",
        version: "0.1.0",
        objective: "Find a small set of strongly supported subjects directly related to the case subject.",
        allowedTools: ["get_subject_association_seeds", "find_accounts_by_indicator", "get_indicator_prevalence", "get_environment_overview", "find_shared_payment_instrument_accounts", "find_reused_product_image_accounts", "get_account_commerce_links", "find_conversation_accounts", "get_account_security_timeline", "get_entity_neighbors", "expand_association_graph", "get_previous_cases", "get_evidence_records"],
        relationGuidance: [
          { type: "shared_device", baseWeight: 0.45, requiresCorroboration: false, enabled: true },
          { type: "shared_ip", baseWeight: 0.2, requiresCorroboration: true, enabled: true },
          { type: "ordinary_transaction", baseWeight: 0.1, requiresCorroboration: true, enabled: true },
          { type: "shared_payment_instrument", baseWeight: 0.6, requiresCorroboration: false, enabled: true },
          { type: "reused_product_image", baseWeight: 0.35, requiresCorroboration: true, enabled: true },
        ],
        search: [
          { key: "max_hops", label: "Max hops", value: 2, min: 1, max: 2 },
          { key: "max_nodes", label: "Max nodes", value: 50, min: 1, max: 100 },
          { key: "lookback_days", label: "Lookback", value: 30, min: 1, max: 365, suffix: "days" },
          { key: "minimum_independent_signals", label: "Independent signals", value: 2, min: 1, max: 10 },
        ],
        budget: [
          { key: "max_turns", label: "Max turns", value: 12, min: 1, max: 50 },
          { key: "max_related_subjects", label: "Related subjects", value: 10, min: 0, max: 100 },
        ],
        stoppingConditions: ["No evidence-backed direct relation remains", "All ambiguous infrastructure links lack corroboration", "The turn, node, or related-subject budget is reached"],
        source: "services/association/policies/focused.json",
      },
      {
        id: "discovery",
        label: "Discovery",
        description: "在明確預算內擴張關聯圖，尋找間接關係與實體群集。",
        policyId: "association-discovery",
        version: "0.1.0",
        objective: "Discover evidence-backed clusters and indirect subjects near the case subject.",
        allowedTools: ["get_subject_association_seeds", "find_accounts_by_indicator", "get_indicator_prevalence", "get_environment_overview", "find_shared_payment_instrument_accounts", "find_reused_product_image_accounts", "get_account_commerce_links", "find_conversation_accounts", "get_account_security_timeline", "get_entity_neighbors", "expand_association_graph", "get_previous_cases", "get_evidence_records"],
        relationGuidance: [
          { type: "shared_device", baseWeight: 0.45, requiresCorroboration: false, enabled: true },
          { type: "shared_ip", baseWeight: 0.2, requiresCorroboration: true, enabled: true },
          { type: "multi_path_cluster", baseWeight: 0.25, requiresCorroboration: false, enabled: true },
          { type: "shared_payment_instrument", baseWeight: 0.6, requiresCorroboration: false, enabled: true },
          { type: "reused_product_image", baseWeight: 0.35, requiresCorroboration: true, enabled: true },
        ],
        search: [
          { key: "max_hops", label: "Max hops", value: 2, min: 1, max: 2 },
          { key: "max_nodes", label: "Max nodes", value: 100, min: 1, max: 100 },
          { key: "lookback_days", label: "Lookback", value: 90, min: 1, max: 365, suffix: "days" },
          { key: "minimum_independent_signals", label: "Independent signals", value: 2, min: 1, max: 10 },
        ],
        budget: [
          { key: "max_turns", label: "Max turns", value: 18, min: 1, max: 50 },
          { key: "max_related_subjects", label: "Related subjects", value: 20, min: 0, max: 100 },
        ],
        stoppingConditions: ["No evidence-backed frontier remains", "New graph expansion has low marginal value", "The turn, node, or related-subject budget is reached"],
        source: "services/association/policies/discovery.json",
      },
    ],
  },
};
