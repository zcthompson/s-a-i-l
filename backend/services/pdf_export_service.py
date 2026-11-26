"""PDF export service using reportlab with customer/department filtering.

Supports user-scoped queries via the ``customer_users`` junction table for
auditor-only read access enforcement.

Report content (detailed report):
- Report Details (customer / assessment scope block)
- Executive Summary (totals, status counts, average/median/min/max, total
  impact, score distribution, top/bottom use cases, cohort trend)
- Last-State Analytics (per use case: latest score, score date, change vs
  the previous scoring round, trend, and the latest AI prediction)
- Department Breakdown (counts, completed count, average score, total impact)
- Use Case Overview (one line per use case incl. score date, delta, timeline)
- Use Case Detail (one block per use case: description, 6-dimension score
  table, score-history trend, latest reasoning + recommendations,
  goals/challenges/pain points, business impact, AI predictions)

All analytic values are derived from persisted application data only —
the ``use_cases`` rows (scores / overall / impact fields), the
``score_history`` table (the authoritative scoring audit trail written by
every real scoring path; per-round reasoning and dimensions), the legacy
``use_cases.score_history`` JSON column (fallback for seeded demo data
that has no table rows), and the ``ai_predictions`` rows (persisted model
output). Nothing is invented for the report.
"""

import io
from datetime import UTC, datetime
from statistics import median
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from backend.models.collaboration import ScoreHistory
from backend.models.use_case import AIPrediction, UseCase
from backend.services.scoring import ScoringService

# Palette (kept from the report)
_DARK = HexColor('#2C3E50')
_GRAY = HexColor('#7F8C8D')
_BLUE = HexColor('#2980B9')
_HEADER_BG = HexColor('#3498DB')
_ROW_BG_A = HexColor('#FFFFFF')
_ROW_BG_B = HexColor('#F8F9FA')
_GRID = HexColor('#BDC3C7')
_BAND_BG = HexColor('#ECF0F1')
_BAND_LABEL_BG = HexColor('#D5DBDB')


def _user_has_dept_access(user_dept: list[str] | None, case_dept: str | None) -> bool:
    """Check if user's department includes the use case's department."""
    if not user_dept or not case_dept:
        return True  # No restrictions
    # Cast to string to handle SQLAlchemy Column types
    case_dept_str = str(case_dept) if case_dept is not None else None
    return case_dept_str in user_dept if case_dept_str else True


def _history_entries(uc: UseCase) -> list[dict[str, Any]]:
    """Normalized, date-sorted history from the legacy JSON column.

    Entries become ``{"date": str, "score": float, "reasoning": str|None,
    "recommendations": list|None}``. Tolerates the key spellings in
    circulation (``date``/``timestamp``/``scored_at`` and
    ``overall_score``/``score``) and skips malformed entries — report
    generation must never crash on a partial history.
    """
    entries: list[dict[str, Any]] = []
    for entry in uc.score_history or []:
        if not isinstance(entry, dict):
            continue
        raw_score = entry.get("overall_score", entry.get("score"))
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        date = entry.get("date") or entry.get("timestamp") or entry.get("scored_at") or ""
        entries.append({
            "date": str(date) if date else "",
            "score": score,
            "reasoning": entry.get("reasoning"),
            "recommendations": entry.get("recommendations"),
        })
    entries.sort(key=lambda item: item["date"])
    return entries


def _last_state(uc: UseCase, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Last-state analytic information for one use case.

    "Last state" = the current scoring state (``overall_score`` /
    ``scored_at``) with movement computed against the *previous* scoring
    round. ``entries`` is the date-sorted history already resolved for
    this use case (authoritative ``score_history`` table rows, or the
    legacy JSON column fallback).

    Semantics: when the most recent history entry matches the current
    overall score (the writer appended the current round as the last
    entry — the seed and this module's own test fixtures do this), the
    previous round is the second-to-last entry. When the current score
    differs, the history's last entry IS the previous round.
    """
    latest = uc.overall_score
    prev: float | None = None
    if entries:
        last_score = entries[-1]["score"]
        if (
            latest is not None
            and last_score is not None
            and abs(float(latest) - float(last_score)) < 0.05
        ):
            prev = entries[-2]["score"] if len(entries) >= 2 else None
        elif last_score is not None:
            prev = last_score
    delta: float | None = None
    if latest is not None and prev is not None:
        delta = round(float(latest) - float(prev), 2)
    trend: str | None = None
    if delta is not None:
        trend = "improving" if delta > 0 else ("declining" if delta < 0 else "stable")
    return {
        "latest": latest,
        "latest_date": uc.scored_at,
        "prev": prev,
        "delta": delta,
        "trend": trend,
    }


def _fmt_date(value) -> str:
    if value is None:
        return "-"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(value)[:10]


def _fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "-"
    return f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {
        "Normal": base["Normal"],
        "Title": ParagraphStyle(
            "CustomTitle", parent=base["Heading1"],
            fontSize=24, leading=28, spaceAfter=30, textColor=_DARK,
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"],
            fontSize=12, leading=16, spaceAfter=20, textColor=_GRAY,
        ),
        "SectionHeader": ParagraphStyle(
            "SectionHeader", parent=base["Heading2"],
            fontSize=14, leading=18, spaceBefore=20, spaceAfter=10, textColor=_BLUE,
        ),
        "UcTitle": ParagraphStyle(
            "UcTitle", parent=base["Normal"],
            fontSize=12, leading=15, spaceBefore=4, spaceAfter=4,
            textColor=_DARK, fontName="Helvetica-Bold",
        ),
        "UcMeta": ParagraphStyle(
            "UcMeta", parent=base["Normal"],
            fontSize=8, leading=10, spaceAfter=6, textColor=_GRAY,
        ),
        "Body": ParagraphStyle(
            "Body", parent=base["Normal"],
            fontSize=9, leading=12, spaceAfter=6,
        ),
        "Bullet": ParagraphStyle(
            "Bullet", parent=base["Normal"],
            fontSize=9, leading=12, leftIndent=10, spaceAfter=2,
        ),
        "Label": ParagraphStyle(
            "Label", parent=base["Normal"],
            fontSize=9, leading=12, spaceBefore=8, spaceAfter=2,
            fontName="Helvetica-Bold", textColor=_DARK,
        ),
    }
    return styles


def _cell_style() -> ParagraphStyle:
    """Compact cell style for table Paragraph cells.

    TableStyle FONTSIZE only affects plain-string cells — Paragraph cells
    default to the 10pt Normal style, which overflows the narrow report
    columns and forces mid-word line breaks. All table Paragraph cells use
    this 8pt style so they render as designed.
    """
    return ParagraphStyle(
        "TableCell", parent=getSampleStyleSheet()["Normal"],
        fontSize=8, leading=10,
    )


def _band_table(rows: list[list], col_widths: list[float]) -> Table:
    """Label/value band table (Report Details / Executive Summary)."""
    data = [
        [Paragraph(str(r[0]), _cell_style()), Paragraph(str(r[1]), _cell_style())]
        for r in rows
    ]
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BAND_BG),
        ("BACKGROUND", (0, 0), (0, -1), _BAND_LABEL_BG),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 1, _GRID),
    ]))
    return table


def _grid_table(header: list[str], rows: list[list], col_widths: list[float],
                align_center_from: int = 1) -> Table:
    """Standard blue-header data table with repeating header row."""
    cell = _cell_style()
    data = [[Paragraph(f"<b>{h}</b>", cell) for h in header]]
    data.extend(rows)
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor('#FFFFFF')),
        ("ALIGN", (align_center_from, 0), (-1, -1), 'CENTER'),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_ROW_BG_A, _ROW_BG_B]),
    ]))
    return table


def export_use_cases_pdf(
    db: Session,
    use_case_ids: list[int] | None = None,
    user_id: str | None = None,
    customer_id: int | None = None,
    report_meta: dict | None = None,
) -> bytes:
    """Export use cases as a detailed PDF report with customer/department filtering.

    ``report_meta`` (from export_service.resolve_export_scope) adds the
    customer/assessment report header and is used for the dynamic title.
    """
    query = db.query(UseCase)

    # Apply ID filter if provided (`is not None`: an explicit empty ID
    # list must export nothing, not widen to the unfiltered set)
    if use_case_ids is not None:
        query = query.filter(UseCase.id.in_(use_case_ids))

    # Apply customer filter if provided
    if customer_id is not None:
        query = query.filter(UseCase.customer_id == customer_id)

    use_cases = query.all()

    # Apply department restrictions if user_id is provided
    if user_id:
        try:
            from backend.models.use_case import User as UserModel
            user = db.query(UserModel).filter(UserModel.username == user_id).first()
            user_dept = user.department if user else None
            if user_dept:
                use_cases = [
                    uc for uc in use_cases
                    if _user_has_dept_access([user_dept], uc.department)
                ]
        except Exception:
            pass  # If user lookup fails, return all use cases

    # AI predictions for the scoped use cases (persisted model output only)
    prediction_map: dict[int, list[AIPrediction]] = {}
    if use_cases:
        scoped_ids = [uc.id for uc in use_cases]
        for pred in (
            db.query(AIPrediction)
            .filter(AIPrediction.use_case_id.in_(scoped_ids))
            .order_by(AIPrediction.id)
            .all()
        ):
            prediction_map.setdefault(pred.use_case_id, []).append(pred)
    for preds in prediction_map.values():
        preds.sort(key=lambda p: p.horizon_days)

    # Score history for the scoped use cases. The ``score_history`` table is
    # the authoritative audit trail (every real scoring path — AI scoring,
    # manual override, history approval — writes it, and the prediction and
    # /history endpoints read it). The legacy ``use_cases.score_history``
    # JSON column is only used as a fallback for use cases that have no
    # table rows (seeded demo data predating the table).
    table_history: dict[int, list[ScoreHistory]] = {}
    if use_cases:
        scoped_ids = [uc.id for uc in use_cases]
        for row in (
            db.query(ScoreHistory)
            .filter(ScoreHistory.use_case_id.in_(scoped_ids))
            .order_by(ScoreHistory.scored_at, ScoreHistory.id)
            .all()
        ):
            table_history.setdefault(row.use_case_id, []).append(row)

    def _history_for(uc: UseCase) -> list[dict[str, Any]]:
        """Date-sorted history entries for one use case (table first)."""
        rows = table_history.get(uc.id)
        if rows:
            return [
                {
                    "date": h.scored_at.isoformat() if h.scored_at else "",
                    "score": float(h.score) if h.score is not None else None,
                    "reasoning": h.reasoning,
                    "recommendations": None,
                }
                for h in rows
                if h.score is not None
            ]
        return _history_entries(uc)

    styles = _build_styles()
    generated = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=1 * inch, bottomMargin=0.9 * inch,
        leftMargin=1 * inch, rightMargin=1 * inch,
    )
    elements: list[Any] = []

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_GRAY)
        canvas.drawString(1 * inch, 0.5 * inch, f"S-A-I-L report — generated {generated}")
        canvas.drawRightString(letter[0] - 1 * inch, 0.5 * inch, f"Page {_doc.page}")
        canvas.restoreState()

    # ── Title (dynamic for customer/assessment-scoped reports) ────────────
    if report_meta and report_meta.get("assessment_name"):
        title_text = "S-A-I-L — Customer Assessment Report"
    elif report_meta:
        title_text = f"S-A-I-L — {report_meta.get('customer_name') or 'Customer'} Report"
    else:
        title_text = "S-A-I-L — Use Case Report"
    elements.append(Paragraph(title_text, styles["Title"]))
    elements.append(Paragraph(f"Generated: {generated}", styles["Subtitle"]))
    elements.append(Spacer(1, 12))

    # ── Report details (customer / assessment context) when scoped ────────
    if report_meta:
        elements.append(Paragraph("Report Details", styles["SectionHeader"]))
        detail_rows = [
            ["Customer", report_meta.get("customer_name") or "-"],
        ]
        if report_meta.get("assessment_name"):
            detail_rows.append(["Assessment", report_meta["assessment_name"]])
            detail_rows.append(["Status", (report_meta.get("assessment_status") or "-").capitalize()])
            detail_rows.append(["Created", report_meta.get("created_at") or "-"])
            if report_meta.get("created_by"):
                detail_rows.append(["Prepared by", report_meta["created_by"]])
            if report_meta.get("archived_at"):
                detail_rows.append(["Archived", report_meta.get("archived_at")])
        if report_meta.get("use_case_count") is not None:
            detail_rows.append(["Use Cases", str(report_meta["use_case_count"])])
        elements.append(_band_table(detail_rows, [1.6 * inch, 4.9 * inch]))
        elements.append(Spacer(1, 14))

    # ── Executive summary ─────────────────────────────────────────────────
    total = len(use_cases)
    scored_ucs = [uc for uc in use_cases if uc.overall_score is not None]
    scores = [float(uc.overall_score) for uc in scored_ucs]
    completed_n = sum(1 for uc in use_cases if uc.status == "completed")
    active_n = sum(1 for uc in use_cases if uc.status == "active")
    draft_n = sum(1 for uc in use_cases if uc.status == "draft")
    total_impact = sum((uc.estimated_savings or 0) + (uc.estimated_revenue or 0) for uc in use_cases)

    buckets = {"0-39": 0, "40-59": 0, "60-79": 0, "80-100": 0}
    for s in scores:
        if s < 40:
            buckets["0-39"] += 1
        elif s < 60:
            buckets["40-59"] += 1
        elif s < 80:
            buckets["60-79"] += 1
        else:
            buckets["80-100"] += 1

    ranked = sorted(scored_ucs, key=lambda uc: float(uc.overall_score), reverse=True)
    top3 = ranked[:3]
    bottom3 = [uc for uc in ranked[-3:] if uc not in top3] if len(ranked) > 3 else []

    deltas = [
        st["delta"]
        for uc in use_cases
        if (st := _last_state(uc, _history_for(uc)))["delta"] is not None
    ]
    if deltas:
        avg_delta = sum(deltas) / len(deltas)
        cohort_word = "improving" if avg_delta > 0 else ("declining" if avg_delta < 0 else "stable")
        cohort_trend = (
            f"Average change vs prior scoring round: {_fmt_delta(avg_delta)} "
            f"({cohort_word}, {len(deltas)} use cases with history)"
        )
    else:
        cohort_trend = "No prior scoring rounds recorded for this set."

    elements.append(Paragraph("Executive Summary", styles["SectionHeader"]))
    summary_rows = [
        ["Total Use Cases", str(total)],
        ["Scored Use Cases", f"{len(scores)}/{total}"],
        ["Status (completed / active / draft)", f"{completed_n} / {active_n} / {draft_n}"],
        ["Average Score", f"{(sum(scores) / len(scores)):.1f}" if scores else "-"],
        ["Median Score", f"{median(scores):.1f}" if scores else "-"],
        ["Min / Max Score", f"{min(scores):.1f} / {max(scores):.1f}" if scores else "-"],
        ["Total Business Impact", f"${total_impact:,.0f}"],
        ["Score Distribution (0-39 / 40-59 / 60-79 / 80-100)",
         f"{buckets['0-39']} / {buckets['40-59']} / {buckets['60-79']} / {buckets['80-100']}"],
    ]
    if top3:
        summary_rows.append(
            ["Top Use Cases", "; ".join(f"{uc.title} ({float(uc.overall_score):.1f})" for uc in top3)]
        )
    if bottom3:
        summary_rows.append(
            ["Bottom Use Cases", "; ".join(f"{uc.title} ({float(uc.overall_score):.1f})" for uc in bottom3)]
        )
    summary_rows.append(["Trend", cohort_trend])
    elements.append(_band_table(summary_rows, [2.4 * inch, 4.1 * inch]))
    elements.append(Spacer(1, 14))

    # ── Last-state analytics ──────────────────────────────────────────────
    if use_cases:
        elements.append(Paragraph("Last-State Analytics", styles["SectionHeader"]))
        elements.append(Paragraph(
            "Current scoring state per use case, with movement versus the previous "
            "scoring round (score history) and the latest AI prediction where one exists.",
            styles["Body"],
        ))
        ls_rows = []
        for uc in sorted(use_cases, key=lambda u: (u.department or "", u.title)):
            st = _last_state(uc, _history_for(uc))
            pred = prediction_map.get(uc.id)
            pred_txt = "-"
            if pred:
                p = pred[0]
                pred_txt = (
                    f"{p.predicted_score:.1f} ({p.horizon_days}d, {p.trend or '-'})"
                )
            ls_rows.append([
                Paragraph(uc.title[:60] if uc.title else "", _cell_style()),
                Paragraph(uc.department or "-", _cell_style()),
                Paragraph((uc.status or "-").capitalize(), _cell_style()),
                Paragraph(f"{st['latest']:.1f}" if st["latest"] is not None else "-", _cell_style()),
                Paragraph(_fmt_date(st["latest_date"]), _cell_style()),
                Paragraph(_fmt_delta(st["delta"]), _cell_style()),
                Paragraph((st["trend"] or "-").capitalize(), _cell_style()),
                Paragraph(pred_txt, _cell_style()),
            ])
        elements.append(_grid_table(
            ["Use Case", "Dept", "Status", "Last Score", "Scored", "vs Prev", "Trend", "AI Forecast"],
            ls_rows,
            [1.45 * inch, 0.85 * inch, 0.75 * inch, 0.6 * inch, 0.75 * inch, 0.6 * inch, 0.75 * inch, 0.75 * inch],
        ))
        elements.append(Spacer(1, 14))

    # ── Department breakdown ──────────────────────────────────────────────
    if use_cases:
        elements.append(Paragraph("Department Breakdown", styles["SectionHeader"]))
        dept_map: dict[str, dict[str, Any]] = {}
        for uc in use_cases:
            key = uc.department or "Unassigned"
            entry = dept_map.setdefault(key, {"count": 0, "completed": 0, "scores": [], "impact": 0.0})
            entry["count"] += 1
            if uc.status == "completed":
                entry["completed"] += 1
            if uc.overall_score is not None:
                entry["scores"].append(float(uc.overall_score))
            entry["impact"] += (uc.estimated_savings or 0) + (uc.estimated_revenue or 0)
        dept_rows = []
        for name in sorted(dept_map, key=lambda n: -dept_map[n]["count"]):
            entry = dept_map[name]
            avg = sum(entry["scores"]) / len(entry["scores"]) if entry["scores"] else None
            dept_rows.append([
                Paragraph(name, _cell_style()),
                Paragraph(str(entry["count"]), _cell_style()),
                Paragraph(str(entry["completed"]), _cell_style()),
                Paragraph(f"{avg:.1f}" if avg is not None else "-", _cell_style()),
                Paragraph(f"${entry['impact']:,.0f}" if entry["impact"] else "-", _cell_style()),
            ])
        elements.append(_grid_table(
            ["Department", "Use Cases", "Completed", "Avg Score", "Total Impact"],
            dept_rows,
            [2.0 * inch, 0.9 * inch, 1.0 * inch, 0.9 * inch, 1.7 * inch],
        ))
        elements.append(Spacer(1, 14))

    # ── Technology Summary ─────────────────────────────────────────────────
    if use_cases:
        elements.append(Paragraph("Technology Summary", styles["SectionHeader"]))
        tech_map: dict[str, dict[str, Any]] = {}
        for uc in use_cases:
            # tech_stack keys
            ts = uc.tech_stack or {}
            if isinstance(ts, dict):
                for key in ts:
                    tech_map[key] = tech_map.get(key, {"count": 0, "usecases": []})
                    tech_map[key]["count"] += 1
                    tech_map[key]["usecases"].append(uc.title)

            # devices
            dev = uc.devices or {}
            if isinstance(dev, dict):
                for key in dev:
                    # normalize device key
                    dkey = f"device_{key}"
                    tech_map[dkey] = tech_map.get(dkey, {"count": 0, "usecases": []})
                    tech_map[dkey]["count"] += 1
                    tech_map[dkey]["usecases"].append(uc.title)

            # software keys
            sw = uc.software or {}
            if isinstance(sw, dict):
                for key in sw:
                    skey = f"software_{key}"
                    tech_map[skey] = tech_map.get(skey, {"count": 0, "usecases": []})
                    tech_map[skey]["count"] += 1
                    tech_map[skey]["usecases"].append(uc.title)

            # vendor
            v = uc.vendor
            if v:
                tech_map[f"vendor_{v}"] = tech_map.get(f"vendor_{v}", {"count": 0, "usecases": []})
                tech_map[f"vendor_{v}"]["count"] += 1
                tech_map[f"vendor_{v}"]["usecases"].append(uc.title)

        # Filter to only entries with counts and sort
        tech_entries = [
            (name, data["count"])
            for name, data in tech_map.items()
            if data["count"] > 0
        ]
        tech_entries.sort(key=lambda x: x[1], reverse=True)

        # Show top 10 technology items
        tech_rows = []
        for name, count in tech_entries[:10]:
            short_name = name.split("_", 1)[-1] if "_" in name else name[:30]
            tech_rows.append([Paragraph(short_name, _cell_style()), Paragraph(str(count), _cell_style())])

        if tech_rows:
            elements.append(_grid_table(
                ["Technology Item", "Use Case Count"],
                tech_rows,
                [4.0 * inch, 1.5 * inch],
            ))
        elements.append(Spacer(1, 14))

    # ── Use case overview ─────────────────────────────────────────────────
    if use_cases:
        elements.append(Paragraph("Use Case Overview", styles["SectionHeader"]))
        ov_rows = []
        for uc in use_cases:
            st = _last_state(uc, _history_for(uc))
            ov_rows.append([
                Paragraph(str(uc.id), _cell_style()),
                Paragraph(uc.title[:45] if uc.title else "", _cell_style()),
                Paragraph(uc.department or "-", _cell_style()),
                Paragraph((uc.status or "-").capitalize(), _cell_style()),
                Paragraph(f"{uc.overall_score:.1f}" if uc.overall_score else "-", _cell_style()),
                Paragraph(_fmt_date(st["latest_date"]), _cell_style()),
                Paragraph(_fmt_delta(st["delta"]), _cell_style()),
                Paragraph(uc.timeline_estimate or "-", _cell_style()),
            ])
        elements.append(_grid_table(
            ["ID", "Title", "Dept", "Status", "Score", "Scored", "vs Prev", "Timeline"],
            ov_rows,
            [0.35 * inch, 1.8 * inch, 0.85 * inch, 0.7 * inch, 0.55 * inch, 0.9 * inch, 0.6 * inch, 0.75 * inch],
        ))
        elements.append(Spacer(1, 14))

    # ── Use case detail (one block per use case) ──────────────────────────
    if use_cases:
        elements.append(Paragraph("Use Case Detail", styles["SectionHeader"]))
        for uc in use_cases:
            block: list[Any] = []
            block.append(Paragraph(f"{uc.id}. {uc.title}", styles["UcTitle"]))
            meta_bits = [
                f"Department: {uc.department or 'Unassigned'}",
                f"Status: {(uc.status or '-').capitalize()}",
            ]
            if uc.assessment is not None:
                meta_bits.append(f"Assessment: {uc.assessment.name}")
            st = _last_state(uc, _history_for(uc))
            if st["latest_date"] is not None:
                meta_bits.append(f"Last scored: {_fmt_date(st['latest_date'])}")
            block.append(Paragraph("  •  ".join(meta_bits), styles["UcMeta"]))
            if uc.description:
                block.append(Paragraph(uc.description, styles["Body"]))

            dims = ScoringService.extract_dimension_scores(uc.scores)
            if dims:
                dim_rows = [
                    [Paragraph(name, _cell_style()),
                     Paragraph(f"{dims[name]:.1f}", _cell_style())]
                    for name in ScoringService.DIMENSIONS_NAME_ORDER if name in dims
                ]
                if uc.overall_score is not None:
                    dim_rows.append([
                        Paragraph("<b>Overall (weighted)</b>", _cell_style()),
                        Paragraph(f"<b>{float(uc.overall_score):.1f}</b>", _cell_style()),
                    ])
                block.append(Paragraph("Dimension Scores (0-100)", styles["Label"]))
                block.append(_grid_table(["Dimension", "Score"], dim_rows,
                                         [4.2 * inch, 1.2 * inch]))

            hist = _history_for(uc)
            if hist:
                hist_rows = []
                prev_score = None
                for entry in hist:
                    date = entry["date"]
                    overall = entry["score"]
                    if overall is None:
                        continue
                    delta = (overall - prev_score) if prev_score is not None else None
                    hist_rows.append([
                        Paragraph(date[:10] or "-", _cell_style()),
                        Paragraph(f"{overall:.1f}", _cell_style()),
                        Paragraph(_fmt_delta(delta), _cell_style()),
                    ])
                    prev_score = overall
                block.append(Paragraph("Score History", styles["Label"]))
                block.append(_grid_table(
                    ["Date", "Overall", "vs Prev"],
                    hist_rows, [1.8 * inch, 1.0 * inch, 1.0 * inch],
                ))
                # Latest scoring reasoning / recommendations: prefer the
                # current scoring payload (uc.scores carries the model's
                # reasoning + recommendations for AI-scored use cases), then
                # the most recent history entry (seeded demo data).
                scores_payload = uc.scores if isinstance(uc.scores, dict) else {}
                latest_reasoning = scores_payload.get("reasoning")
                latest_recs = scores_payload.get("recommendations")
                if not latest_reasoning or not latest_recs:
                    last_entry = hist[-1]
                    if last_entry is not None:
                        if not latest_reasoning and last_entry.get("reasoning"):
                            latest_reasoning = last_entry["reasoning"]
                        if not latest_recs and last_entry.get("recommendations"):
                            latest_recs = last_entry["recommendations"]
                if latest_reasoning:
                    block.append(Paragraph("Latest Scoring Reasoning", styles["Label"]))
                    block.append(Paragraph(str(latest_reasoning), styles["Body"]))
                if latest_recs:
                    block.append(Paragraph("Recommendations", styles["Label"]))
                    for rec in latest_recs:
                        block.append(Paragraph(f"• {rec}", styles["Bullet"]))

            for label, items in (
                ("Goals", uc.goals), ("Challenges", uc.challenges), ("Pain Points", uc.pain_points),
            ):
                if items:
                    block.append(Paragraph(label, styles["Label"]))
                    for item in items:
                        block.append(Paragraph(f"• {item}", styles["Bullet"]))

            if (
                uc.impact_category or uc.impact_description
                or uc.estimated_savings or uc.estimated_revenue or uc.timeline_estimate
            ):
                block.append(Paragraph("Business Impact", styles["Label"]))
                uc_impact = (uc.estimated_savings or 0) + (uc.estimated_revenue or 0)
                block.append(_band_table([
                    ["Category", uc.impact_category or "-"],
                    ["Description", uc.impact_description or "-"],
                    ["Estimated Savings", f"${uc.estimated_savings:,.0f}" if uc.estimated_savings else "-"],
                    ["Estimated Revenue", f"${uc.estimated_revenue:,.0f}" if uc.estimated_revenue else "-"],
                    ["Total Impact", f"${uc_impact:,.0f}" if uc_impact else "-"],
                    ["Timeline Estimate", uc.timeline_estimate or "-"],
                ], [1.6 * inch, 4.9 * inch]))

            preds = prediction_map.get(uc.id)
            if preds:
                block.append(Paragraph("AI Predictions (model-generated)", styles["Label"]))
                pred_rows = []
                for p in preds:
                    pred_rows.append([
                        Paragraph(f"{p.horizon_days} days", _cell_style()),
                        Paragraph(f"{p.predicted_score:.1f}", _cell_style()),
                        Paragraph(_fmt_delta(p.score_change), _cell_style()),
                        Paragraph((p.trend or "-").capitalize(), _cell_style()),
                        Paragraph(f"{p.confidence:.2f}" if p.confidence is not None else "-", _cell_style()),
                        Paragraph(p.model or "-", _cell_style()),
                    ])
                block.append(_grid_table(
                    ["Horizon", "Predicted", "Change", "Trend", "Confidence", "Model"],
                    pred_rows,
                    [0.9 * inch, 0.9 * inch, 0.8 * inch, 0.9 * inch, 0.9 * inch, 1.4 * inch],
                ))

            block.append(Spacer(1, 14))
            elements.append(KeepTogether(block))

    # Build PDF
    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.getvalue()
