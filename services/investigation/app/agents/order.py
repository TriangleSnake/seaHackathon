"""Order, transaction, payment, and fulfillment investigation agent."""

from app.agents.base import DomainAgent


class OrderAgent(DomainAgent):
    name = "order"
    primary_subject_types = ("order", "transaction")
    item_score_weights = {
        "transaction_activity": 0.30,
        "payment_activity": 0.25,
        "fulfillment_activity": 0.15,
        "refund_dispute_activity": 0.15,
        "account_activity": 0.15,
    }
    allowed_tools = (
        "get_evidence_records",
        "get_environment_overview",
        "get_account_activity",
        "get_account_commerce_links",
        "find_shared_payment_instrument_accounts",
        "get_account_security_timeline",
        "find_shared_ip_accounts",
        "find_shared_device_accounts",
        "get_entity_neighbors",
        "get_previous_cases",
    )
    evidence_terms = (
        "transaction",
        "order",
        "payment",
        "delivery",
        "refund",
        "dispute",
        "report",
        "amount",
    )
    trigger_terms = (
        "transaction",
        "order",
        "payment",
        "delivery",
        "refund",
        "dispute",
        "report",
    )
