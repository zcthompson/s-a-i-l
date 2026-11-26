"""Read-only partner pipeline snapshots: line money and identified opportunities.

Amounts are source-labelled USD estimates. Opportunity currency and forecast
category are descriptive attributes, never conversion or weighting inputs.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, tuple_
from sqlalchemy.orm import load_only

from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline

PIPELINE_CALC_VERSION = "pipeline-read-model/1"
PRECISION_NOTE = (
    "amounts are stored as float from the source CSV; totals are computed with Decimal "
    "over stored values and rounded at the boundary; the original file is retained "
    "on the import row as evidence"
)


def stage_class(raw: str | None) -> str:
    """Map only documented open stages and explicitly closed won/lost labels."""
    normalized = (raw or "").strip().lower()
    if normalized in {"discover", "validate", "propose", "negotiate"}:
        return "open"
    if normalized.startswith("closed") and "won" in normalized:
        return "won"
    if normalized.startswith("closed") and "lost" in normalized:
        return "lost"
    return "unknown"


def _iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _amount(rows, attribute):
    recorded = [Decimal(str(getattr(row, attribute))) for row in rows
                if getattr(row, attribute) is not None]
    included = len(recorded)
    excluded = len(rows) - included
    total = sum(recorded, Decimal(0)).quantize(Decimal("0.01")) if recorded else None
    if not rows:
        coverage = "no_data"
    elif not recorded:
        coverage = "all_unknown"
    elif excluded:
        coverage = "partial"
    elif total == 0:
        coverage = "recorded_zero"
    else:
        coverage = "quantified"
    return {
        "total": float(total) if total is not None else None,
        "coverage": coverage,
        "lines_included": included,
        "lines_excluded": excluded,
    }


def _attributes(rows, attribute):
    # Missing categorical attributes have no source value to report.
    counts = Counter(getattr(row, attribute) for row in rows
                     if (getattr(row, attribute) or "").strip())
    return dict(sorted(counts.items()))


def summarize_pipeline_rows(rows, batch=None, *, as_of=None):
    """Summarize ONE account/batch's lines, also used for frozen import evidence.

    Raw null conflict values render as ``None``; dates render as ISO dates.
    Lines without an identity contribute money but never opportunity counts.
    """
    opportunities = defaultdict(list)
    unidentified = 0
    for row in rows:
        number = (row.opportunity_number or "").strip()
        if number:
            opportunities[number].append(row)
        else:
            unidentified += 1
    stages = {key: 0 for key in ("open", "won", "lost", "unknown")}
    ambiguous = []
    for number, lines in sorted(opportunities.items()):
        conflicts = []
        for label, values in (
            ("stage", {line.opp_stage for line in lines}),
            ("close_date", {line.close_date.isoformat() if line.close_date else None
                            for line in lines}),
        ):
            if len(values) > 1:
                rendered = ", ".join(repr(value) for value in sorted(
                    values, key=lambda value: (value is not None, value or ""),
                ))
                conflicts.append(f"{label}: {rendered}")
        if conflicts:
            ambiguous.append({"opportunity_number": number, "conflicts": conflicts})
        stages["unknown" if conflicts else stage_class(lines[0].opp_stage)] += 1
    stages["unknown_stage_values"] = sorted({
        row.opp_stage for row in rows
        if (row.opp_stage or "").strip() and stage_class(row.opp_stage) == "unknown"
    })
    non_usd = sum(row.currency_code != "USD" for row in rows)
    return {
        "calculation_version": PIPELINE_CALC_VERSION,
        "as_of": as_of or _iso(datetime.now(UTC)),
        "source": {
            "source_type": "partner_pipeline",
            "import_id": batch.id,
            "source_file": batch.file_name,
            "imported_at": _iso(batch.created_at),
            "imported_by": batch.imported_by,
            "note": "imported_at is import time, not a business effective date",
        } if batch is not None and rows else None,
        "currency_basis": "USD (source-labelled line estimates; never converted)",
        "currency_codes": sorted({row.currency_code for row in rows
                                  if (row.currency_code or "").strip()}),
        "currency_note": (
            f"{non_usd} line(s) carry a non-USD/blank opportunity currency code; "
            "amounts remain source-labelled USD"
        ) if non_usd else None,
        "grain": {
            "line_count": len(rows),
            "opportunity_count": len(opportunities),
            "unidentified_lines": unidentified,
            "ambiguous_opportunities": ambiguous,
        },
        "stages": stages,
        "amounts": {"acv": _amount(rows, "est_acv_usd"), "tcv": _amount(rows, "est_tcv_usd")},
        "forecast_categories": _attributes(rows, "forecast_category"),
        "reporting": {
            "fiscal_quarters": _attributes(rows, "fiscal_quarter"),
            "net_new_vs_renewal": _attributes(rows, "net_new_vs_renewal"),
        },
        "precision_note": PRECISION_NOTE,
    }


def pipeline_summaries_for(db, customer_ids) -> dict[int, dict]:
    """Latest retained snapshot per scoped account, in at most three queries.

    The scope is supplied by an authorized caller. An empty scope reads nothing.
    Original CSV bytes are deliberately not loaded on this read path.
    """
    ids = sorted(set(customer_ids))
    if not ids:
        return {}
    latest = db.query(
        PartnerPipeline.customer_id,
        func.max(PartnerPipeline.import_id).label("import_id"),
    ).filter(PartnerPipeline.customer_id.in_(ids)).group_by(PartnerPipeline.customer_id).subquery()
    selected = dict(db.query(latest).order_by(latest.c.customer_id).all())
    grouped = defaultdict(list)
    batches = {}
    if selected:
        rows = db.query(PartnerPipeline).filter(
            tuple_(PartnerPipeline.customer_id, PartnerPipeline.import_id).in_(
                sorted(selected.items()),
            ),
        ).order_by(PartnerPipeline.customer_id, PartnerPipeline.source_row, PartnerPipeline.id).all()
        for row in rows:
            grouped[row.customer_id].append(row)
        batches = {
            batch.id: batch for batch in db.query(IntelligenceImport).options(load_only(
                IntelligenceImport.id, IntelligenceImport.file_name,
                IntelligenceImport.created_at, IntelligenceImport.imported_by,
            )).filter(IntelligenceImport.id.in_(sorted(set(selected.values()))))
            .order_by(IntelligenceImport.id).all()
        }
    as_of = _iso(datetime.now(UTC))
    return {
        cid: summarize_pipeline_rows(grouped[cid], batches.get(selected.get(cid)), as_of=as_of)
        for cid in ids
    }


def pipeline_summary_for(db, customer_id) -> dict:
    return pipeline_summaries_for(db, [customer_id])[customer_id]


SNAPSHOT_COMPARE_CALC_VERSION = "pipeline-snapshot-compare/1"
RENEWAL_CALC_VERSION = "pipeline-renewal/1"
COMPARISON_NOTES = [
    "Observed-removed opportunities are absent from the later retained snapshot; this is not evidence of closed-lost, zero pipeline, or churn.",
    "No velocity or win rate is supported by snapshot observations alone.",
    "imported_at values are import times, not business effective dates.",
]
RENEWAL_NOTE = (
    "Current contract end dates are vendor-reported renewal evidence from the selected snapshot; "
    "an opportunity close is never support expiry; exposure is source-labelled USD line totals (never converted)"
)
DATED_BUCKETS = ("overdue", "within_30", "within_60", "within_90", "within_180")


def _batch_metadata(batch):
    return {
        "import_id": batch.id, "source_file": batch.file_name,
        "imported_at": _iso(batch.created_at), "imported_by": batch.imported_by,
    }


def _batches_for(db, ids):
    return {batch.id: batch for batch in db.query(IntelligenceImport).options(load_only(
        IntelligenceImport.id, IntelligenceImport.file_name,
        IntelligenceImport.created_at, IntelligenceImport.imported_by,
    )).filter(IntelligenceImport.id.in_(ids)).all()}


def pipeline_snapshot_history(db, customer_id):
    """Retained account observations, newest first, without loading CSV bytes."""
    from sqlalchemy import case, distinct

    number = func.trim(PartnerPipeline.opportunity_number)
    counts = db.query(
        PartnerPipeline.import_id, func.count(PartnerPipeline.id),
        func.count(distinct(case((number != "", number)))),
    ).filter(PartnerPipeline.customer_id == customer_id).group_by(
        PartnerPipeline.import_id,
    ).order_by(PartnerPipeline.import_id.desc()).all()
    if not counts:
        return []
    batches = _batches_for(db, [item[0] for item in counts])
    return [dict(_batch_metadata(batches[bid]), line_count=lines,
                 opportunity_count=opportunities, selected=(index == 0))
            for index, (bid, lines, opportunities) in enumerate(counts)]


def _opportunity_lines(rows):
    grouped = defaultdict(list)
    for row in rows:
        number = (row.opportunity_number or "").strip()
        if number:
            grouped[number].append(row)
    for lines in grouped.values():
        lines.sort(key=lambda row: (row.source_row is None, row.source_row or 0, row.id))
    return grouped


def _name(lines):
    return next((line.opportunity_name for line in lines
                 if (line.opportunity_name or "").strip()), None)


def _linkage(lines):
    return {"line_ids": sorted(line.id for line in lines),
            "line_source_rows": sorted(line.source_row for line in lines
                                       if line.source_row is not None)}


def _reported_renewal(lines):
    return any((line.net_new_vs_renewal or "").strip().lower() == "renewal" for line in lines)


def _observed_opportunity(number, lines):
    first = lines[0]
    ambiguous = bool(summarize_pipeline_rows(lines)["grain"]["ambiguous_opportunities"])
    return {
        "opportunity_number": number, "opportunity_name": _name(lines),
        "stage_raw": first.opp_stage, "stage_class": "unknown" if ambiguous else stage_class(first.opp_stage),
        "close_date": first.close_date.isoformat() if first.close_date else None,
        "est_acv_usd": _amount(lines, "est_acv_usd")["total"],
        "est_tcv_usd": _amount(lines, "est_tcv_usd")["total"],
        "reported_renewal": _reported_renewal(lines), **_linkage(lines),
    }


def compare_pipeline_snapshots(rows_from, rows_to, batch_from, batch_to, *, as_of=None):
    """Compare identified opportunities; no cross-snapshot line matching is claimed."""
    left, right = _opportunity_lines(rows_from), _opportunity_lines(rows_to)
    conflicts = []
    for rows in (rows_from, rows_to):
        conflicts.append({item["opportunity_number"]: item["conflicts"] for item in
                          summarize_pipeline_rows(rows)["grain"]["ambiguous_opportunities"]})
    result = {
        "calculation_version": SNAPSHOT_COMPARE_CALC_VERSION,
        "as_of": as_of or _iso(datetime.now(UTC)),
        "from": dict(_batch_metadata(batch_from), note="imported_at is import time, not a business effective date"),
        "to": dict(_batch_metadata(batch_to), note="imported_at is import time, not a business effective date"),
        "opportunity_count": {"from": len(left), "to": len(right)},
        "unidentified": {"from": len(rows_from) - sum(map(len, left.values())),
                         "to": len(rows_to) - sum(map(len, right.values()))},
        "added": [_observed_opportunity(n, right[n]) for n in sorted(right.keys() - left.keys())],
        "observed_removed": [_observed_opportunity(n, left[n]) for n in sorted(left.keys() - right.keys())],
        "stage_changes": [], "close_date_changes": [], "name_changes": [],
        "amount_changes": [], "unchanged": [], "ambiguity": [], "notes": list(COMPARISON_NOTES),
    }
    for number in sorted(left.keys() | right.keys()):
        if number in conflicts[0] or number in conflicts[1]:
            result["ambiguity"].append({
                "opportunity_number": number,
                "from_conflicts": conflicts[0].get(number, []),
                "to_conflicts": conflicts[1].get(number, []),
                "note": "conflicting source values in a snapshot — stage/close deltas for it are suppressed (visible, not fabricated)",
            })
    for number in sorted(left.keys() & right.keys()):
        before, after = left[number], right[number]
        links = {"line_ids_from": sorted(row.id for row in before),
                 "line_ids_to": sorted(row.id for row in after)}
        base = {"opportunity_number": number, **links}
        changed = False
        if number not in conflicts[0] and number not in conflicts[1]:
            old, new = before[0].opp_stage, after[0].opp_stage
            if (old or "").strip().lower() != (new or "").strip().lower():
                changed = True
                result["stage_changes"].append(dict(base, from_stage=old, to_stage=new,
                    from_class=stage_class(old), to_class=stage_class(new)))
            old_date, new_date = before[0].close_date, after[0].close_date
            if old_date and new_date and old_date != new_date:
                changed = True
                result["close_date_changes"].append(dict(base,
                    from_close_date=old_date.isoformat(), to_close_date=new_date.isoformat(),
                    slip_days=(new_date - old_date).days))
        old_name, new_name = _name(before), _name(after)
        if (old_name or "").strip().casefold() != (new_name or "").strip().casefold():
            changed = True
            result["name_changes"].append(dict(base, name_from=old_name, name_to=new_name))
        amounts = {}
        for key, attribute in (("acv", "est_acv_usd"), ("tcv", "est_tcv_usd")):
            old_amount, new_amount = _amount(before, attribute)["total"], _amount(after, attribute)["total"]
            amounts[key] = {"from": old_amount, "to": new_amount,
                            "delta": float(Decimal(str(new_amount)) - Decimal(str(old_amount)))
                            if old_amount is not None and new_amount is not None else None}
        if any(item["from"] != item["to"] for item in amounts.values()):
            changed = True
            result["amount_changes"].append(dict(base, **amounts))
        if not changed:
            result["unchanged"].append(number)
    return result


class _RenewalCard(dict):
    """Keep raw lines privately for portfolio sums before boundary rounding."""

    def __init__(self, values, rows):
        super().__init__(values)
        self.rows = rows


def renewal_attention_for_rows(rows, *, reference_date=None, as_of=None):
    """Vendor-reported end-date attention, one card per identified opportunity.

    Pure row reads cannot supply batch metadata; the scoped callers attach the
    selected snapshot, including when it contains no renewal evidence.
    """
    reference_date = reference_date or datetime.now(UTC).date()
    buckets = {key: [] for key in DATED_BUCKETS}
    buckets.update(beyond_180_count=0, unknown_date=[])
    for number, lines in sorted(_opportunity_lines(rows).items()):
        dates = sorted({row.current_contract_end_date for row in lines
                        if row.current_contract_end_date is not None})
        reported = _reported_renewal(lines)
        if not dates and not reported:
            continue
        card_date = dates[0] if dates else None
        days = (card_date - reference_date).days if card_date else None
        if days is not None and days > 180:
            buckets["beyond_180_count"] += 1
            continue
        bucket = ("unknown_date" if days is None else "overdue" if days < 0 else
                  "within_30" if days <= 30 else "within_60" if days <= 60 else
                  "within_90" if days <= 90 else "within_180")
        original = sorted({row.contract_end_date for row in lines if row.contract_end_date})
        buckets[bucket].append(_RenewalCard({
            "opportunity_number": number, "opportunity_name": _name(lines),
            "renewal_date": card_date.isoformat() if card_date else None, "days": days,
            "lines": len(lines), "est_acv": _amount(lines, "est_acv_usd"),
            "est_tcv": _amount(lines, "est_tcv_usd"), "reported_renewal": reported,
            "net_new_vs_renewal_values": sorted({row.net_new_vs_renewal for row in lines
                                                 if (row.net_new_vs_renewal or "").strip()}),
            "conflicting_end_dates": [value.isoformat() for value in dates] if len(dates) > 1 else [],
            "original_contract_end": original[0].isoformat() if original else None,
            **_linkage(lines),
        }, lines))
    for bucket in (*DATED_BUCKETS, "unknown_date"):
        buckets[bucket].sort(key=lambda card: (card["days"] if card["days"] is not None else 0,
                                              card["opportunity_number"]))
    return {
        "calculation_version": RENEWAL_CALC_VERSION,
        "as_of": as_of or _iso(datetime.now(UTC)), "reference_date": reference_date.isoformat(),
        "snapshot": None, "buckets": buckets,
        "counts": {**{key: len(buckets[key]) for key in (*DATED_BUCKETS, "unknown_date")},
                   "beyond_180": buckets["beyond_180_count"]},
        "note": RENEWAL_NOTE,
    }


def renewal_attention_summaries_for(db, customer_ids, *, reference_date=None, as_of=None):
    """Latest retained account snapshots, in at most three scoped queries."""
    ids = sorted(set(customer_ids))
    if not ids:
        return {}
    reference_date = reference_date or datetime.now(UTC).date()
    as_of = as_of or _iso(datetime.now(UTC))
    selected = dict(db.query(PartnerPipeline.customer_id, func.max(PartnerPipeline.import_id))
                    .filter(PartnerPipeline.customer_id.in_(ids))
                    .group_by(PartnerPipeline.customer_id).all())
    grouped = defaultdict(list)
    batches = {}
    if selected:
        rows = db.query(PartnerPipeline).filter(
            tuple_(PartnerPipeline.customer_id, PartnerPipeline.import_id).in_(sorted(selected.items())),
        ).order_by(PartnerPipeline.customer_id, PartnerPipeline.source_row, PartnerPipeline.id).all()
        for row in rows:
            grouped[row.customer_id].append(row)
        batches = _batches_for(db, sorted(set(selected.values())))
    result = {}
    for cid in ids:
        attention = renewal_attention_for_rows(grouped[cid], reference_date=reference_date, as_of=as_of)
        if cid in selected:
            batch = batches[selected[cid]]
            attention["snapshot"] = {key: value for key, value in _batch_metadata(batch).items()
                                     if key != "imported_by"}
        result[cid] = attention
    return result


def _renewal_cards(attention):
    return [card for bucket in (*DATED_BUCKETS, "unknown_date")
            for card in attention["buckets"][bucket]]


def _card_exposure(cards, key):
    """Combine card totals using Decimal, retaining original line coverage."""
    attribute = "est_acv_usd" if key == "est_acv" else "est_tcv_usd"
    return _amount([row for card in cards for row in card.rows], attribute)


class _PortfolioRenewal(dict):
    """Public rollup plus in-process per-account rows from the same batched read.

    The attribute is deliberately outside the JSON mapping, so it cannot leak
    account-level implementation data into the public rollup shape.
    """

    def __init__(self, values, account_summaries):
        super().__init__(values)
        self.account_summaries = account_summaries


def portfolio_renewal_rollup(db, customer_ids, *, reference_date=None, as_of=None):
    from backend.models.use_case import Customer

    ids = sorted(set(customer_ids))
    reference_date = reference_date or datetime.now(UTC).date()
    as_of = as_of or _iso(datetime.now(UTC))
    summaries = renewal_attention_summaries_for(db, ids, reference_date=reference_date, as_of=as_of)
    scoped_cards = [(cid, card) for cid, summary in summaries.items()
                    for card in _renewal_cards(summary)]
    cards = [card for _, card in scoped_cards]
    dated = sorted(((cid, card) for cid, card in scoped_cards if card["renewal_date"] is not None),
                   key=lambda item: (item[1]["renewal_date"], item[0], item[1]["opportunity_number"]))
    next_cards = dated[:10]
    names = {customer.id: customer.name for customer in db.query(Customer).options(
        load_only(Customer.id, Customer.name),
    ).filter(Customer.id.in_(sorted({cid for cid, _ in next_cards}))).all()} if next_cards else {}
    rows = {}
    for cid, summary in summaries.items():
        account_cards = _renewal_cards(summary)
        account_dates = [card["renewal_date"] for card in account_cards if card["renewal_date"]]
        rows[cid] = {"counts": summary["counts"],
                     "acv_exposure": _card_exposure(account_cards, "est_acv")["total"],
                     "next_renewal": min(account_dates) if account_dates else None}
    return _PortfolioRenewal({
        "calculation_version": RENEWAL_CALC_VERSION, "as_of": as_of,
        "reference_date": reference_date.isoformat(), "accounts_scoped": len(ids),
        "accounts_with_renewal_evidence": sum(any(summary["counts"][key] for key in DATED_BUCKETS)
                                              for summary in summaries.values()),
        "accounts_no_data": sum(summary["snapshot"] is None for summary in summaries.values()),
        "counts": {key: sum(summary["counts"][key] for summary in summaries.values())
                   for key in (*DATED_BUCKETS, "beyond_180", "unknown_date")},
        "exposure": {"acv": _card_exposure(cards, "est_acv"), "tcv": _card_exposure(cards, "est_tcv")},
        "next_renewals": [{"customer_id": cid,
                           "customer_name": names[cid],
                           **{key: card[key] for key in ("opportunity_number", "renewal_date", "days")}}
                          for cid, card in next_cards],
    }, rows)
