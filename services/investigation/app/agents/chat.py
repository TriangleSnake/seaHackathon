"""Chat and URL investigation agent."""

from app.agents.base import DomainAgent


class ChatAgent(DomainAgent):
    name = "chat"
    primary_subject_types = ("message",)
    item_score_weights = {
        "message_content": 0.35,
        "conversation_context": 0.20,
        "url_attachment_risk": 0.20,
        "participant_account_activity": 0.15,
        "transaction_context": 0.10,
    }
    allowed_tools = (
        "get_evidence_records",
        "get_environment_overview",
        "get_account_activity",
        "find_conversation_accounts",
        "find_accounts_by_indicator",
        "get_indicator_prevalence",
        "get_virustotal_reputation",
        "get_account_security_timeline",
        "find_shared_ip_accounts",
        "find_shared_device_accounts",
        "get_entity_neighbors",
        "get_previous_cases",
    )
    evidence_terms = ("message", "conversation", "text", "url", "domain")
    trigger_terms = ("chat", "message", "phishing", "url", "link")
