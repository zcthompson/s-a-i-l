"""Customer technology brief generation tool for sales enrichment.

Generates a sales-ready customer brief that summarizes technology
tracking data across use cases for a given customer.
"""

from datetime import datetime
from typing import Any

from backend.services import sales_access
from backend.services.customer_access import require_account_read_service
from sqlalchemy.orm import Session


def generate_customer_brief(
    db: Session,
    user: dict,
    customer_id: int,
    use_cases: list[dict] | None = None,
) -> dict:
    """Generate a sales-ready customer brief with technology tracking.
    
    Args:
        db: Session used by the central account-read policy
        user: Authenticated user context
        customer_id: The customer ID to generate brief for
        use_cases: Optional pre-fetched use case data (dict format from to_dict())
    
    Returns:
        Dict containing the customer brief with technology summary
    """
    require_account_read_service(db, user, customer_id)
    # If use_cases not provided, would query from DB
    # For now, work with provided data
    if use_cases is None:
        use_cases = []
    
    # A single-account brief cannot admit another account's supplied content,
    # even when the caller has permission to read both accounts.
    accessible_cids = _get_accessible_customer_ids(db, user)
    use_cases = [
        uc for uc in use_cases
        if uc.get("customer_id") == customer_id
        and (accessible_cids is None or uc.get("customer_id") in accessible_cids)
    ]
    
    # Separate scored and unscored use cases
    scored_ucs = [uc for uc in use_cases if uc.get("overall_score") is not None]
    unscored_ucs = [uc for uc in use_cases if uc.get("overall_score") is None]
    
    # Technology aggregation
    tech_stack_counts: dict[str, int] = {}
    device_types: dict[str, int] = {}
    software_categories: dict[str, int] = {}
    vendor_counts: dict[str, int] = {}
    
    for uc in scored_ucs:
        # tech_stack
        ts = uc.get("tech_stack") or {}
        if isinstance(ts, dict):
            for key in ts:
                tech_stack_counts[key] = tech_stack_counts.get(key, 0) + 1
        
        # devices
        dev = uc.get("devices") or {}
        if isinstance(dev, dict):
            for key in dev:
                device_types[key] = device_types.get(key, 0) + 1
        
        # software
        sw = uc.get("software") or {}
        if isinstance(sw, dict):
            for key in sw:
                if isinstance(sw[key], list):
                    for tool in sw[key]:
                        software_categories[tool] = software_categories.get(tool, 0) + 1
                else:
                    software_categories[key] = software_categories.get(key, 0) + 1
        
        # vendor
        v = uc.get("vendor")
        if v:
            vendor_counts[v] = vendor_counts.get(v, 0) + 1
    
    # Determine most common tech vendors
    top_vendors = sorted(vendor_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Count use cases by technology presence
    ucs_with_tech = sum(
        1 for uc in scored_ucs
        if uc.get("tech_stack")
        or uc.get("devices")
        or uc.get("software")
        or uc.get("vendor")
    )
    
    # Build the brief
    brief = {
        "customer_id": customer_id,
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "total_use_cases": len(use_cases),
            "scored_use_cases": len(scored_ucs),
            "unscored_use_cases": len(unscored_ucs),
            "use_cases_with_technology_tracking": ucs_with_tech,
            "technology_coverage": round(
                ucs_with_tech / len(scored_ucs) * 100, 1
            ) if scored_ucs else 0,
        },
        "technology_landscape": {
            "common_tech_stacks": _top_tech_stacks(tech_stack_counts),
            "common_devices": _top_devices(device_types),
            "common_software": _top_software(software_categories),
            "top_vendors": [v[0] for v in top_vendors],
            "vendor_counts": dict(top_vendors),
        },
        "key_use_cases": _summarize_key_use_cases(scored_ucs),
        "sales_recommendations": _generate_sales_recommendations(
            tech_stack_counts,
            device_types,
            software_categories,
            vendor_counts,
            scored_ucs,
        ),
    }
    
    return brief


def _get_accessible_customer_ids(db: Session, user: dict) -> set[int] | None:
    """Resolve central read scope; None means an unrestricted system admin."""
    if sales_access.is_unrestricted(user):
        return None
    return sales_access.customer_scope(user, db)


def _top_tech_stacks(tech_stack_counts: dict[str, int]) -> list[dict[str, Any]]:
    """Get top technology stacks by usage count."""
    sorted_stacks = sorted(tech_stack_counts.items(), key=lambda x: x[1], reverse=True)
    return [
        {"tech": stack, "use_case_count": count}
        for stack, count in sorted_stacks[:10]
    ]


def _top_devices(device_types: dict[str, int]) -> list[dict[str, Any]]:
    """Get top device types by usage count."""
    sorted_devices = sorted(device_types.items(), key=lambda x: x[1], reverse=True)
    return [
        {"device": dev, "use_case_count": count}
        for dev, count in sorted_devices[:10]
    ]


def _top_software(software_categories: dict[str, int]) -> list[dict[str, Any]]:
    """Get top software/tools by usage count."""
    sorted_software = sorted(software_categories.items(), key=lambda x: x[1], reverse=True)
    return [
        {"software": tool, "use_case_count": count}
        for tool, count in sorted_software[:10]
    ]


def _summarize_key_use_cases(scored_ucs: list[dict]) -> list[dict]:
    """Summarize key use cases with technology focus."""
    summaries = []
    for uc in scored_ucs[:10]:  # Top 10 by score
        title = uc.get("title", "Unknown")
        dept = uc.get("department", "Unassigned")
        score = uc.get("overall_score", 0)
        tech_stack = uc.get("tech_stack", {})
        vendor = uc.get("vendor", "")
        
        summaries.append({
            "title": title,
            "department": dept,
            "overall_score": score,
            "vendor": vendor,
            "tech_stack": tech_stack if isinstance(tech_stack, str) else str(tech_stack)[:80],
        })
    
    return summaries


def _generate_sales_recommendations(
    tech_stack_counts: dict[str, int],
    device_types: dict[str, int],
    software_categories: dict[str, int],
    vendor_counts: dict[str, int],
    scored_ucs: list[dict],
) -> list[str]:
    """Generate sales recommendations based on technology tracking data."""
    recommendations = []
    
    # Analyze common patterns
    if tech_stack_counts:
        top_stack = max(tech_stack_counts.items(), key=lambda x: x[1])
        recommendations.append(
            f"Customer has {top_stack[1]} use cases using {top_stack[0]} — "
            "position relevant integration/extension solutions"
        )
    
    if vendor_counts:
        top_vendor = max(vendor_counts.items(), key=lambda x: x[1])
        if top_vendor[1] > 1:
            recommendations.append(
                f"{top_vendor[1]} use cases work with {top_vendor[0]} — "
                "offer vendor-specific add-ons or migration paths"
            )
    
    if device_types:
        recommendations.append(
            f"Device landscape includes {len(device_types)} tracked categories — "
            "hardware compatibility and optimization opportunities"
        )
    
    if software_categories:
        top_software = max(software_categories.items(), key=lambda x: x[1])
        recommendations.append(
            f"Frequent software: {top_software[0]} across {top_software[1]} use cases — "
            "licensing optimization and tool integration"
        )
    
    # Score-based recommendations
    if scored_ucs:
        high_score_ucs = [uc for uc in scored_ucs if uc.get("overall_score", 0) > 70]
        if high_score_ucs:
            recommendations.append(
                f"{len(high_score_ucs)} high-scoring use cases — "
                "upsell premium features and advanced capabilities"
            )
    
    return recommendations


# CLI entry point
def main():
    """CLI entry point for generating customer briefs."""
    import sys

    from backend.config import get_settings
    from backend.database import create_engine
    from sqlalchemy.orm import sessionmaker
    
    settings = get_settings()
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    
    if len(sys.argv) < 3:
        print("Usage: python -m backend.tools.customer_brief <customer_id> <username>")
        sys.exit(1)
    
    customer_id = int(sys.argv[1])
    from backend.models.use_case import UseCase, User
    from backend.services.membership_service import actor_context

    with Session() as session:
        actor = session.query(User).filter_by(username=sys.argv[2], is_active=1, approved=1).first()
        if actor is None:
            raise SystemExit("An active, approved user is required")
        user = actor_context(session, actor.id)
        require_account_read_service(session, user, customer_id)
        use_cases = session.query(UseCase).filter(UseCase.customer_id == customer_id).all()
        brief = generate_customer_brief(session, user, customer_id, [uc.to_dict() for uc in use_cases])

        import json
        print(json.dumps(brief, indent=2))


if __name__ == "__main__":
    main()
