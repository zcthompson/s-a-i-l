"""Global admin dashboard routes.

Provides aggregated statistics across all customers for admin users.
Requires authentication and admin role.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services.customer_stats_service import CustomerStatsService
from backend.services.user_service import UserService

router = APIRouter(prefix="/api/global-admin", tags=["global-admin"])


@router.get("/stats")
def get_global_admin_stats(
    req: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Get global admin statistics across all customers.
    
    This endpoint requires admin privileges. It aggregates statistics
    across all customers in the system.
    
    Returns:
        Global statistics including:
        - total_customers: Count of all customers
        - total_use_cases: Total use cases across all customers
        - average_score: Average AI readiness score
        - total_savings: Aggregate savings across all customers
        - total_revenue: Aggregate revenue across all customers
        - customers: List of customer summaries with their stats
    """
    user = get_user_from_request(req)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check if user has admin role
    if not user.get("is_admin", False):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required for global admin access"
        )
    
    # Get global stats
    global_stats = CustomerStatsService.get_global_stats(db)
    # Add global user counts (total/active/pending/admin + role breakdown)
    global_stats.update(UserService.get_user_stats(db))
    
    return global_stats


@router.get("/summary")
def get_global_admin_summary(
    req: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Get a simplified global admin summary for dashboard display.
    
    Returns a high-level summary of the system-wide metrics.
    """
    user = get_user_from_request(req)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not user.get("is_admin", False):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required"
        )
    
    global_stats = CustomerStatsService.get_global_stats(db)
    
    return {
        "total_customers": global_stats["total_customers"],
        "total_use_cases": global_stats["total_use_cases"],
        "average_score": global_stats["average_score"],
        "total_impact": global_stats["total_impact"],
        "customers_count": len(global_stats.get("customers", [])),
        "top_customers": global_stats.get("customers", [])[:5],
    }
