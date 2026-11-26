"""Enhanced stats with department breakdown, status distribution, and score trends.

Supports customer-scoped queries via optional ``customer_id`` parameter and
user-scoped queries via the ``customer_users`` junction table.
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from backend.models.use_case import UseCase


class StatsService:
    """Statistics and reporting for use cases."""

    @staticmethod
    def _apply_scope(
        query: "Any",
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ):
        """Apply caller authorization to any UseCase query.

        ``customer_ids`` (non-admin union scope) and ``customer_id`` (explicit
        single-customer filter) compose. An **empty** ``customer_ids`` list is
        a terminal "no data authorized" scope: it is applied via
        ``customer_id == -1`` so the query matches nothing rather than silently
        widening to the global set (the export ``use_case_ids is not None``
        idiom). ``None`` means "no restriction" and is only ever passed by
        authorized global (admin) callers.
        """
        if customer_ids is not None:
            if customer_ids:
                query = query.filter(UseCase.customer_id.in_(customer_ids))
            else:
                query = query.filter(UseCase.customer_id == -1)
        if customer_id is not None:
            query = query.filter(UseCase.customer_id == customer_id)
        return query

    @staticmethod
    def get_aggregate_stats(
        db: Session,
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ) -> dict:
        """Get comprehensive aggregate statistics.

        Args:
            db: Database session
            customer_id: Optional single-customer filter (admin explicit scope)
            customer_ids: Optional authorized customer-union filter. ``None``
                = no restriction (admin global); an empty list = no data
                authorized (non-admin with no assignment). Every field below
                — including the ``average_score`` query — is scoped identically.
        """
        query = StatsService._apply_scope(db.query(UseCase), customer_id, customer_ids)

        total = query.count()
        scored = StatsService._apply_scope(
            db.query(UseCase), customer_id, customer_ids
        ).filter(UseCase.overall_score.isnot(None)).count()
        # average_score MUST use the same authorized scope: the
        # previous global ``avg`` leaked cross-customer averages to non-admins.
        avg_score = (
            StatsService._apply_scope(
                db.query(func.avg(UseCase.overall_score)), customer_id, customer_ids
            )
            .filter(UseCase.overall_score.isnot(None))
            .scalar()
        ) or 0.0

        # Department breakdown
        dept_query = (
            db.query(
                UseCase.department,
                func.count(UseCase.id).label('count'),
                func.avg(UseCase.overall_score).label('avg_score'),
                func.sum(
                    func.coalesce(UseCase.estimated_savings, 0) +
                    func.coalesce(UseCase.estimated_revenue, 0)
                ).label('total_impact')
            )
            .group_by(UseCase.department)
        )
        dept_query = StatsService._apply_scope(dept_query, customer_id, customer_ids)
        dept_stats = dept_query.all()

        # Status distribution
        status_query = (
            db.query(
                UseCase.status,
                func.count(UseCase.id).label('count')
            )
            .group_by(UseCase.status)
        )
        status_query = StatsService._apply_scope(status_query, customer_id, customer_ids)
        status_stats = status_query.all()

        # Top use cases by score
        top_query = db.query(UseCase).filter(UseCase.overall_score.isnot(None))
        top_query = StatsService._apply_scope(top_query, customer_id, customer_ids)
        top_use_cases = top_query.order_by(desc(UseCase.overall_score)).limit(5).all()

        # Impact summary
        savings_query = StatsService._apply_scope(
            db.query(func.sum(UseCase.estimated_savings)), customer_id, customer_ids
        )
        revenue_query = StatsService._apply_scope(
            db.query(func.sum(UseCase.estimated_revenue)), customer_id, customer_ids
        )
        total_savings = savings_query.scalar() or 0
        total_revenue = revenue_query.scalar() or 0

        return {
            "total_use_cases": total,
            "scored_use_cases": scored,
            "average_score": round(avg_score, 1),
            "by_department": {
                dept or "Unassigned": {
                    "count": count,
                    "avg_score": round(avg_score_val, 1) if avg_score_val else 0,
                    "total_impact": round(total_impact, 2),
                }
                for dept, count, avg_score_val, total_impact in dept_stats
            },
            "by_status": {
                status: count
                for status, count in status_stats
            },
            "top_use_cases": [
                {
                    "id": uc.id,
                    "title": uc.title,
                    "overall_score": uc.overall_score,
                    "department": uc.department,
                    "status": uc.status,
                }
                for uc in top_use_cases
            ],
            "impact_summary": {
                "total_savings": round(total_savings, 2),
                "total_revenue": round(total_revenue, 2),
                "total_impact": round(total_savings + total_revenue, 2),
            },
        }

    @staticmethod
    def customer_readiness_aggregates(db: Session, customer_id: int) -> dict:
        """Compute readiness aggregates in SQL over the COMPLETE customer
        dataset.

        Returns ``{"total_use_cases", "scored_use_cases", "average_score"}``
        for every use case of the customer — no row cap, so counts and the
        average stay correct past any arbitrary fetch limit (the previous
        readiness computation fetched ``limit=1000`` rows and presented them
        as customer-wide metrics). Other customers' records never enter the
        aggregates (customer isolation).
        """
        total = (
            db.query(UseCase).filter(UseCase.customer_id == customer_id).count()
        )
        scored = (
            db.query(UseCase)
            .filter(
                UseCase.customer_id == customer_id,
                UseCase.overall_score.isnot(None),
            )
            .count()
        )
        avg = (
            db.query(func.avg(UseCase.overall_score))
            .filter(
                UseCase.customer_id == customer_id,
                UseCase.overall_score.isnot(None),
            )
            .scalar()
        )
        return {
            "total_use_cases": total,
            "scored_use_cases": scored,
            "average_score": round(avg, 2) if avg is not None else 0,
        }

    @staticmethod
    def get_score_trends(
        db: Session,
        days: int = 30,
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ) -> list[dict]:
        """Get score trends over time.

        Args:
            db: Database session
            days: Number of days to look back
            customer_id: Optional single-customer filter (admin explicit scope)
            customer_ids: Optional authorized customer-union filter:
                ``None`` = global (admin only), empty list = no data authorized.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        scores_query = (
            db.query(UseCase)
            .filter(
                UseCase.scored_at.isnot(None),
                UseCase.scored_at >= cutoff,
            )
        )
        scores_query = StatsService._apply_scope(scores_query, customer_id, customer_ids)

        scores = scores_query.order_by(UseCase.scored_at).all()

        # Group by date
        daily_scores = {}
        for score in scores:
            date = score.scored_at.strftime('%Y-%m-%d')
            if date not in daily_scores:
                daily_scores[date] = []
            daily_scores[date].append(score.overall_score or 0)

        trends = [
            {
                "date": date,
                "count": len(scores),
                "avg_score": sum(scores) / len(scores),
                "max_score": max(scores),
                "min_score": min(scores),
            }
            for date, scores in sorted(daily_scores.items())
        ]

        return trends

    @staticmethod
    def export_to_csv(
        db: Session,
        use_case_ids: list[int] | None = None,
        customer_id: int | None = None,
    ) -> str:
        """Export use cases to CSV format.

        Args:
            db: Database session
            use_case_ids: Optional filter by IDs
            customer_id: Optional customer scope
        """
        query = db.query(UseCase)
        # `is not None`: an explicit empty ID list (e.g. the intersection of
        # an assessment scope with out-of-round IDs) must export nothing,
        # not silently widen to the unfiltered set.
        if use_case_ids is not None:
            query = query.filter(UseCase.id.in_(use_case_ids))
        if customer_id is not None:
            query = query.filter(UseCase.customer_id == customer_id)

        use_cases = query.all()

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'ID', 'Title', 'Description', 'Department', 'Status',
            'Goals', 'Challenges', 'Pain Points',
            'Impact Category', 'Impact Description',
            'Estimated Savings', 'Estimated Revenue', 'Timeline Estimate',
            'Overall Score', 'Scored At', 'Created At', 'Updated At'
        ])

        # Data
        for uc in use_cases:
            writer.writerow([
                uc.id,
                uc.title,
                uc.description or '',
                uc.department or '',
                uc.status,
                '; '.join(uc.goals or []),
                '; '.join(uc.challenges or []),
                '; '.join(uc.pain_points or []),
                uc.impact_category or '',
                uc.impact_description or '',
                uc.estimated_savings or 0,
                uc.estimated_revenue or 0,
                uc.timeline_estimate or '',
                uc.overall_score or '',
                uc.scored_at.strftime('%Y-%m-%d %H:%M:%S') if uc.scored_at else '',
                uc.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                uc.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])

        return output.getvalue()

    @staticmethod
    def export_excel(
        db: Session,
        use_case_ids: list[int] | None = None,
        customer_id: int | None = None,
        report_meta: dict | None = None,
    ) -> bytes:
        """Export use cases to an Excel workbook with multiple sheets.

        Args:
            db: Database session
            use_case_ids: Optional filter by IDs
            customer_id: Optional customer scope; if None returns global
            report_meta: Optional customer/assessment context (from
                export_service.resolve_export_scope) for the report header

        All sheets are computed from the same scoped query set — the
        breakdown sheets never mix in rows outside the export scope.
        """
        import io

        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        def _scoped(query):
            """Apply the export scope to any UseCase query.

            ``use_case_ids is not None`` (not truthiness): an explicit
            empty ID list must select nothing, never widen to global.
            """
            if use_case_ids is not None:
                query = query.filter(UseCase.id.in_(use_case_ids))
            if customer_id is not None:
                query = query.filter(UseCase.customer_id == customer_id)
            return query

        query = _scoped(db.query(UseCase))
        use_cases = query.all()

        wb = Workbook()

        # --- Helper styles ---
        header_font = Font(bold=True, size=11)
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font_white = Font(bold=True, color="FFFFFF", size=11)
        section_font = Font(bold=True, size=12, underline="single")
        center_align = Alignment(horizontal="center", vertical="center")
        wrap_align = Alignment(wrap_text=True, vertical="top")

        def style_header_row(ws, row_num, max_col):
            for col in range(1, max_col + 1):
                cell = ws.cell(row=row_num, column=col)
                cell.font = header_font_white
                cell.fill = header_fill
                cell.alignment = center_align

        def style_section(ws, row_num, text, col_span=5):
            cell = ws.cell(row=row_num, column=1, value=text)
            cell.font = section_font
            ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=col_span)

        # --- Sheet 1: Use Cases ---
        ws = wb.active
        ws.title = "Use Cases"

        sheet_title = "S-A-I-L — Use Cases"
        if report_meta:
            if report_meta.get("assessment_name"):
                sheet_title = (
                    f"S-A-I-L — {report_meta.get('customer_name') or 'Customer'} "
                    f"— {report_meta['assessment_name']} ({report_meta.get('assessment_status') or 'assessment'})"
                )
            elif report_meta.get("customer_name"):
                sheet_title = f"S-A-I-L — {report_meta['customer_name']}"
        style_section(ws, 1, sheet_title, col_span=17)
        ws.cell(row=3, column=1, value="ID").font = header_font_white
        ws.cell(row=3, column=2, value="Title").font = header_font_white
        ws.cell(row=3, column=3, value="Description").font = header_font_white
        ws.cell(row=3, column=4, value="Department").font = header_font_white
        ws.cell(row=3, column=5, value="Status").font = header_font_white
        ws.cell(row=3, column=6, value="Goals").font = header_font_white
        ws.cell(row=3, column=7, value="Challenges").font = header_font_white
        ws.cell(row=3, column=8, value="Pain Points").font = header_font_white
        ws.cell(row=3, column=9, value="Impact Category").font = header_font_white
        ws.cell(row=3, column=10, value="Impact Description").font = header_font_white
        ws.cell(row=3, column=11, value="Est. Savings").font = header_font_white
        ws.cell(row=3, column=12, value="Est. Revenue").font = header_font_white
        ws.cell(row=3, column=13, value="Timeline").font = header_font_white
        ws.cell(row=3, column=14, value="Overall Score").font = header_font_white
        ws.cell(row=3, column=15, value="Scored At").font = header_font_white
        ws.cell(row=3, column=16, value="Created At").font = header_font_white
        ws.cell(row=3, column=17, value="Updated At").font = header_font_white
        style_header_row(ws, 3, 17)

        for i, uc in enumerate(use_cases, start=4):
            row = [
                uc.id,
                uc.title,
                uc.description or "",
                uc.department or "",
                uc.status,
                "; ".join(uc.goals or []),
                "; ".join(uc.challenges or []),
                "; ".join(uc.pain_points or []),
                uc.impact_category or "",
                uc.impact_description or "",
                uc.estimated_savings or 0,
                uc.estimated_revenue or 0,
                uc.timeline_estimate or "",
                uc.overall_score or "",
                uc.scored_at.strftime("%Y-%m-%d %H:%M:%S") if uc.scored_at else "",
                uc.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                uc.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            ]
            for col_idx, val in enumerate(row, 1):
                cell = ws.cell(row=i, column=col_idx, value=val)
                cell.alignment = wrap_align

        # Column widths
        for col in range(1, 18):
            ws.column_dimensions[chr(64 + col)].width = 20 if col < 6 else 30

        # --- Sheet 2: Department Breakdown ---
        from sqlalchemy import desc, func

        dept_stats = (
            _scoped(
                db.query(
                    UseCase.department,
                    func.count(UseCase.id).label("count"),
                    func.avg(UseCase.overall_score).label("avg_score"),
                    func.sum(func.coalesce(UseCase.estimated_savings, 0) + func.coalesce(UseCase.estimated_revenue, 0)).label("total_impact"),
                )
            )
            .group_by(UseCase.department)
            .order_by(desc(func.count(UseCase.id)))
            .all()
        )

        ws2 = wb.create_sheet("Department Breakdown")
        style_section(ws2, 1, "S-A-I-L — Department Breakdown", col_span=5)
        ws2.cell(row=3, column=1, value="Department").font = header_font_white
        ws2.cell(row=3, column=2, value="Count").font = header_font_white
        ws2.cell(row=3, column=3, value="Avg Score").font = header_font_white
        ws2.cell(row=3, column=4, value="Total Impact ($)").font = header_font_white
        ws2.cell(row=3, column=5, value="% of Total").font = header_font_white
        style_header_row(ws2, 3, 5)

        total_use_cases = len(use_cases)
        for i, (dept, count, avg_score_val, total_impact) in enumerate(dept_stats, start=4):
            dept_name = dept or "Unassigned"
            pct = (count / total_use_cases * 100) if total_use_cases > 0 else 0
            row_data = [
                dept_name,
                count,
                round(avg_score_val or 0, 1),
                round(total_impact, 2),
                f"{pct:.1f}%",
            ]
            for col_idx, val in enumerate(row_data, 1):
                ws2.cell(row=i, column=col_idx, value=val)
                ws2.cell(row=i, column=col_idx).alignment = center_align

        for col in range(1, 6):
            ws2.column_dimensions[chr(64 + col)].width = 22

        # --- Sheet 3: Status Distribution ---
        from sqlalchemy import func

        status_stats = (
            _scoped(
                db.query(UseCase.status, func.count(UseCase.id).label("count"))
            )
            .group_by(UseCase.status)
            .all()
        )

        ws3 = wb.create_sheet("Status Distribution")
        style_section(ws3, 1, "S-A-I-L — Status Distribution", col_span=4)
        ws3.cell(row=3, column=1, value="Status").font = header_font_white
        ws3.cell(row=3, column=2, value="Count").font = header_font_white
        ws3.cell(row=3, column=3, value="% of Total").font = header_font_white
        ws3.cell(row=3, column=4, value="Average Score").font = header_font_white
        style_header_row(ws3, 3, 4)

        for i, (status, count) in enumerate(status_stats, start=4):
            pct = (count / total_use_cases * 100) if total_use_cases > 0 else 0
            avg = (
                _scoped(
                    db.query(func.avg(UseCase.overall_score))
                )
                .filter(UseCase.status == status, UseCase.overall_score.isnot(None))
                .scalar()
            ) or 0
            row_data = [status, count, f"{pct:.1f}%", round(avg, 1)]
            for col_idx, val in enumerate(row_data, 1):
                ws3.cell(row=i, column=col_idx, value=val)
                ws3.cell(row=i, column=col_idx).alignment = center_align

        for col in range(1, 5):
            ws3.column_dimensions[chr(64 + col)].width = 22

        # --- Sheet 4: Top Use Cases ---
        top_use_cases = (
            _scoped(db.query(UseCase))
            .filter(UseCase.overall_score.isnot(None))
            .order_by(desc(UseCase.overall_score))
            .limit(5)
            .all()
        )

        ws4 = wb.create_sheet("Top Use Cases")
        style_section(ws4, 1, "S-A-I-L — Top 5 Use Cases by Score", col_span=6)
        ws4.cell(row=3, column=1, value="Rank").font = header_font_white
        ws4.cell(row=3, column=2, value="Title").font = header_font_white
        ws4.cell(row=3, column=3, value="Overall Score").font = header_font_white
        ws4.cell(row=3, column=4, value="Department").font = header_font_white
        ws4.cell(row=3, column=5, value="Status").font = header_font_white
        ws4.cell(row=3, column=6, value="Scored At").font = header_font_white
        style_header_row(ws4, 3, 6)

        for i, uc in enumerate(top_use_cases, start=4):
            row_data = [
                i - 3,
                uc.title,
                uc.overall_score,
                uc.department or "",
                uc.status,
                uc.scored_at.strftime("%Y-%m-%d %H:%M:%S") if uc.scored_at else "",
            ]
            for col_idx, val in enumerate(row_data, 1):
                ws4.cell(row=i, column=col_idx, value=val)
                ws4.cell(row=i, column=col_idx).alignment = center_align

        for col in range(1, 7):
            ws4.column_dimensions[chr(64 + col)].width = 20 if col < 2 else 28

        # --- Sheet 5: Impact Summary ---
        total_savings = _scoped(db.query(func.sum(UseCase.estimated_savings))).scalar() or 0
        total_revenue = _scoped(db.query(func.sum(UseCase.estimated_revenue))).scalar() or 0

        ws5 = wb.create_sheet("Impact Summary")
        style_section(ws5, 1, "S-A-I-L — Impact Summary", col_span=2)
        ws5.cell(row=3, column=1, value="Metric").font = header_font_white
        ws5.cell(row=3, column=2, value="Value ($)").font = header_font_white
        style_header_row(ws5, 3, 2)

        for i, (label, value) in enumerate([
            ("Total Savings", round(total_savings, 2)),
            ("Total Revenue", round(total_revenue, 2)),
            ("Total Impact", round(total_savings + total_revenue, 2)),
            ("Total Use Cases", total_use_cases),
            ("Scored Use Cases", _scoped(db.query(UseCase)).filter(UseCase.overall_score.isnot(None)).count()),
        ], start=4):
            ws5.cell(row=i, column=1, value=label).font = header_font
            ws5.cell(row=i, column=2, value=value)
            ws5.cell(row=i, column=2).alignment = center_align

        for col in range(1, 3):
            ws5.column_dimensions[chr(64 + col)].width = 25

        # Save to bytes
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()
