export type DetectionSubjectType = "account" | "shop" | "product" | "order" | "transaction" | "message";
export type DetectorType = "rule_based" | "anomaly" | "llm_classifier" | "ml_classifier";

export interface DetectionComponentPolicy {
  id: string;
  type: DetectorType;
  version: string;
  enabled: boolean;
  failure_mode: "continue" | "fail";
  config: Record<string, unknown>;
}

export interface DetectionPolicy {
  version: string;
  default_checks: DetectorType[];
  components: DetectionComponentPolicy[];
  rule_based: {
    active_report_statuses: string[];
    chat_request_phrases: string[];
    chat_negations: string[];
    risk_domain_suffixes: string[];
    sensitive_security_events: string[];
    access_window_minutes: number;
    reused_image_min_products: number;
    delivery_claim_terms: string[];
  };
  anomaly: {
    payment_instruments_per_hour: number;
    login_countries_per_day: number;
    login_devices_per_day: number;
    messages_per_hour: number;
    listings_per_hour: number;
    disputes_per_week: number;
  };
  llm_classifier: { confidence_threshold: number };
}

export interface DetectionPolicyVersion {
  version: string;
  document: DetectionPolicy;
  active: boolean;
  source: "human" | "evolution" | string;
  created_at: string;
}

export interface DetectionRequest {
  subject: { type: DetectionSubjectType; id: string };
  trigger_context?: { source?: "patrol" | "manual" | "scheduled" | "api"; reason?: string | null };
  requested_checks?: DetectorType[];
  policy_ref?: { type: "detection"; version: string };
}

export interface DetectionComponentResult {
  component_id: string;
  detector: DetectorType;
  version: string;
  status: "completed" | "abstained" | "unavailable" | "failed";
  trigger_count: number;
  latency_ms: number;
  reason?: string | null;
}

export interface DetectionResult {
  detection_id: string;
  subject: DetectionRequest["subject"];
  policy_ref: { type: "detection"; version: string };
  detected: boolean;
  triggers: Array<{ type: string; detector: DetectorType; rule_id?: string | null; reason: string; raw_result?: Record<string, unknown> | null; evidence_refs: string[] }>;
  evidence: Array<{ id: string; source: string; type: string; ref_id?: string | null; observed_at?: string | null; data: Record<string, unknown> }>;
  component_results: DetectionComponentResult[];
}

export interface DetectionStatus {
  service: string;
  reachable: boolean;
  ready: boolean;
  status: "ready" | "degraded" | "unavailable";
  dependencies: Record<string, string>;
  latencyMs: number;
  checkedAt: string;
  error?: string;
}

export interface DetectionApiError {
  error?: { code?: string; message?: string; request_id?: string };
  detail?: string;
}
