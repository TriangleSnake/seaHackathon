"""Marketplace shop, seller, and listing investigation agent."""

from app.agents.base import DomainAgent


class MarketplaceInfoAgent(DomainAgent):
    name = "marketplace_info"
    primary_subject_types = ("shop", "product")
    item_score_weights = {
        "listing_content": 0.25,
        "price_status_history": 0.20,
        "image_reuse": 0.15,
        "reviews_reports": 0.20,
        "seller_account_activity": 0.20,
    }
    allowed_tools = (
        "get_evidence_records",
        "get_environment_overview",
        "get_subject_association_seeds",
        "get_account_activity",
        "get_account_commerce_links",
        "find_reused_product_image_accounts",
        "find_shared_payment_instrument_accounts",
        "find_shared_ip_accounts",
        "find_shared_device_accounts",
        "get_entity_neighbors",
        "get_previous_cases",
    )
    evidence_terms = (
        "shop",
        "product",
        "marketplace",
        "price",
        "review",
        "seller",
        "listing",
        "image",
    )
    trigger_terms = (
        "marketplace",
        "shop",
        "product",
        "listing",
        "counterfeit",
        "seller",
    )
