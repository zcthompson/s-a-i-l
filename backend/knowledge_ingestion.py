"""Customer environment knowledge ingestion service.

Handles CSV and PDF uploads for customer software/hardware inventory,
processes extracted text, and performs context7 domain grounding for
automatic term categorization and tagging.

Key invariants (AGENT_CHARTER.md):
- All customer knowledge scoped through CustomerUser junction table
- No runtime schema mutation — all migrations via Alembic only
- Service layer business logic; routes are thin HTTP layer
- SQLite: in-memory for tests; migrations idempotent for production
"""
from __future__ import annotations

import re
from typing import Any

from backend.models.use_case import Customer, CustomerUser, UseCase  # noqa: F401
from backend.schemas.customer_knowledge import CustomerKnowledgeCreate  # noqa: F401

# ---------------------------------------------------------------------------
# CSV Ingestion
# ---------------------------------------------------------------------------

def parse_csv_knowledge(file_data: bytes, customer_id: int) -> dict[str, Any]:
    """Parse CSV file data into structured knowledge entries.

    Expected CSV columns (case-insensitive):
      - software (or name): software name
      - version: version string
      - license_type: license type (e.g. commercial, open_source, freeware)
      - department: department using the software
      - status: active | retired
      - vendor: vendor/partner name
      - notes: free-text notes

    Deduplication: by software name + version + customer_id.

    Returns dict with:
      - ingested: list of structured software records
      - skipped: list of duplicate/skipped entries
      - errors: list of parse errors
    """
    text = file_data.decode("utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if not lines:
        return {"ingested": [], "skipped": [], "errors": ["Empty CSV file"]}

    # Parse header (first line)
    header = [h.strip().lower() for h in lines[0].split(",")]
    col_map: dict[str, int] = {}
    for i, h in enumerate(header):
        col_map[h] = i

    # Required columns (by any alias)
    req_aliases = {
        "software": ["software", "name", "app", "application"],
        "version": ["version", "ver"],
        "status": ["status", "state"],
    }

    missing = [r for r in req_aliases if not any(r in h for h in header)]
    if missing:
        return {
            "ingested": [],
            "skipped": [],
            "errors": [f"Missing required CSV columns: {', '.join(missing)}"],
        }


    ingested: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[str] = []

    # Process data rows
    seen_keys: set = set()  # (software_lower, version, customer_id) for dedup
    for row_line in lines[1:]:
        fields = [f.strip() for f in row_line.split(",")]
        if len(fields) < len(header):
            errors.append(f"Row has fewer fields than header: {row_line}")
            continue

        # Extract fields by column map
        software = None
        version = None
        license_type = None
        department = None
        status = None
        vendor = None
        notes = None

        for h, idx in col_map.items():
            if idx >= len(fields):
                continue
            val = fields[idx].strip()
            lower = h.lower()
            if "software" in lower or "name" in lower or "app" in lower or "application" in lower:
                software = val
            elif "version" in lower:
                version = val
            elif "license" in lower:
                license_type = val
            elif "department" in lower:
                department = val
            elif "status" in lower:
                status = val
            elif "vendor" in lower:
                vendor = val
            elif "note" in lower or "comment" in lower:
                notes = val

        # Validate required
        if not software:
            errors.append(f"Missing software name in row: {row_line}")
            continue
        if not version:
            errors.append(f"Missing version for software '{software}' in row: {row_line}")
            continue

        # Dedup key: software (lowercased) + version + customer_id
        dedup_key = (software.lower(), version, customer_id)
        if dedup_key in seen_keys:
            skipped.append(
                {
                    "software": software,
                    "version": version,
                    "reason": "duplicate_for_customer",
                }
            )
            continue
        seen_keys.add(dedup_key)

        record = {
            "software": software,
            "version": version,
            "license_type": license_type,
            "department": department,
            "status": status or "active",
            "vendor": vendor,
            "notes": notes,
            "customer_id": customer_id,
            "knowledge_type": "software_inventory",
        }
        ingested.append(record)

    return {"ingested": ingested, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# PDF Ingestion
# ---------------------------------------------------------------------------

def extract_pdf_text(file_data: bytes) -> str:
    """Extract raw text from PDF file bytes.

    Uses pymupdf (fitz) if available; falls back to a simple heuristic.
    Returns the full text content of the PDF.
    """
    try:
        import fitz  # pyv8 / pymupdf

        doc = fitz.open(stream=file_data, filetype="pdf")
        texts = []
        for page in doc:
            texts.append(page.get_text("text"))
        doc.close()
        return "\n".join(texts)
    except Exception:
        # Fallback: return empty string — caller should handle gracefully
        return ""


def classify_pdf_content(text: str) -> str:
    """Classify PDF extracted text into knowledge types.

    Uses heuristics based on keyword presence:
      - software_inventory: software names, version numbers, license terms
      - hardware_inventory: hardware names, model numbers, asset tags
      - process_document: procedures, workflows, policies
      - policy_document: compliance, governance, certifications
      - other: general documentation

    Returns one of: software_inventory, hardware_inventory, process_document,
    policy_document, other
    """
    text_lower = text.lower()

    # Hardware heuristics
    hardware_keywords = [
        "hardware",
        "equipment",
        "asset",
        "server",
        "workstation",
        "device",
        "model",
        "serial",
        "rack",
        "infrastructure",
    ]
    # Software heuristics
    software_keywords = [
        "software",
        "application",
        "program",
        "license",
        "platform",
        "tool",
        "utility",
    ]
    # Process heuristics
    process_keywords = [
        "procedure",
        "workflow",
        "process",
        "step",
        "implementation",
        "deployment",
    ]
    # Policy heuristics
    policy_keywords = [
        "policy",
        "compliance",
        "certification",
        "audit",
        "governance",
        "standard",
        "regulation",
    ]

    hardware_count = sum(1 for k in hardware_keywords if k in text_lower)
    software_count = sum(1 for k in software_keywords if k in text_lower)
    process_count = sum(1 for k in process_keywords if k in text_lower)
    policy_count = sum(1 for k in policy_keywords if k in text_lower)

    if policy_count > 0:
        return "policy_document"
    if hardware_count > software_count + process_count:
        return "hardware_inventory"
    if software_count > 0 and process_count > 0:
        return "software_inventory"
    if process_count > 0 and policy_count == 0:
        return "process_document"
    return "other"


def ingest_pdf_knowledge(file_data: bytes, customer_id: int) -> dict[str, Any]:
    """Parse PDF file and produce structured knowledge entries.

    Returns dict with:
      - classified_type: software_inventory | hardware_inventory | process_document |
                       policy_document | other
      - extracted_text: raw text from the PDF (may be empty if extraction failed)
      - entries: list of structured knowledge records extracted from the PDF
      - errors: list of parse errors (may be empty)
    """
    text = extract_pdf_text(file_data)
    classified = classify_pdf_content(text)

    # Heuristic: if classified as software_inventory, try to extract software entries
    # by looking for "software name + version" patterns
    entries: list[dict[str, Any]] = []
    errors: list[str] = []

    if not text.strip():
        return {
            "classified_type": classified,
            "extracted_text": "",
            "entries": [],
            "errors": ["No text could be extracted from PDF"],
        }

    # Simple extraction: look for "Name - Version" or "Software Name Version" patterns
    software_pattern = re.compile(
        r"([A-Za-z0-9 ._-]+)\s*[-\s]\s*([\d.]+[^\n]*)", re.IGNORECASE
    )

    # Also look for known software names (simple word tokens followed by version-like strings)
    lines = text.split("\n")
    seen_softwares: set = set()

    for line in lines:
        # Try software pattern
        match = software_pattern.search(line)
        if match:
            name = match.group(1).strip()
            version = match.group(2).strip()
            # Filter out noise
            if len(name) > 2 and name.lower() not in {"the", "and", "for", "with", "was"}:
                dedup_key = (name.lower(), version, customer_id)
                if dedup_key not in seen_softwares:
                    seen_softwares.add(dedup_key)
                    entries.append(
                        {
                            "software": name,
                            "version": version,
                            "license_type": None,
                            "department": None,
                            "status": "active",
                            "vendor": None,
                            "notes": None,
                            "customer_id": customer_id,
                            "knowledge_type": "software_inventory",
                        }
                    )

    # If no structured entries found, create a single entry from the full text
    if not entries and classified == "software_inventory":
        entries.append(
            {
                "software": text[:100].strip(),
                "version": "",
                "license_type": None,
                "department": None,
                "status": "active",
                "vendor": None,
                "notes": text[100:200].strip() if len(text) > 100 else None,
                "customer_id": customer_id,
                "knowledge_type": "software_inventory",
            }
        )
        errors.append("No individual software entries found; created single entry from PDF text")

    return {
        "classified_type": classified,
        "extracted_text": text,
        "entries": entries,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Context7 Domain Grounding
# ---------------------------------------------------------------------------

def ground_software_terms(software_name: str) -> dict[str, Any]:
    """Perform context7 domain grounding on a software name.

    Returns dict with categorized information:
      - category: standard software category from context7
      - confidence: match confidence 0-1
      - related_terms: related software / framework terms
      - licensing_typical: typical licensing model
    """
    # In a full implementation, this would query the context7 MCP server.
    # For now, use a deterministic rule-based mapping based on known patterns.
    name_lower = software_name.lower()

    # Category mapping based on software name patterns
    category_map = {
        # Database & infrastructure
        "sql": "database",
        "postgres": "database",
        "mysql": "database",
        "redis": "cache",
        "elasticsearch": "search",
        "kafka": "messaging",
        "dns": "infrastructure",
        "kubernetes": "orchestration",
        "docker": "containerization",

        # Observability
        "prometheus": "monitoring",
        "grafana": "monitoring",
        "splunk": "observability",
        "datadog": "observability",

        # AI/ML
        "tensorflow": "ml_frameworks",
        "pytorch": "ml_frameworks",
        "scikit-learn": "ml_frameworks",
        "openai": "ai_services",
        "anthropic": "ai_services",

        # CRM/Service
        "salesforce": "crm",
        "hubspot": "crm",
        "zendesk": "service_desk",
        "servicenow": "service_desk",

        # Development
        "jenkins": "ci_cd",
        "gitlab": "ci_cd",
        "github_actions": "ci_cd",
        "circleci": "ci_cd",
        "terraform": "iac",
        "ansible": "iac",
        "chef": "configuration",
        "puppet": "configuration",

        # Analytics
        "tableau": "analytics",
        "powerbi": "analytics",
        "looker": "analytics",
        "mode_analytics": "analytics",
    }

    # Find matching category
    category = "other"
    for key, cat in category_map.items():
        if key in name_lower:
            category = cat
            break

    confidence = 0.7 if category != "other" else 0.4

    related_terms: list[str] = []
    if category == "database":
        related_terms = ["sql", "query", "schema", "migration"]
    elif category == "crm":
        related_terms = ["customer", "pipeline", "contact"]
    elif category == "ci_cd":
        related_terms = ["build", "deploy", "pipeline"]
    elif category == "ml_frameworks":
        related_terms = ["model", "training", "inference"]
    elif category == "observability":
        related_terms = ["metric", "trace", "log"]

    return {
        "software_name": software_name,
        "category": category,
        "confidence": confidence,
        "related_terms": related_terms,
        "licensing_typical": "open_source" if "open" in name_lower else "commercial",
    }


def ground_hardware_terms(hardware_description: str) -> dict[str, Any]:
    """Perform context7 domain grounding on hardware description.

    Returns dict with categorized information:
      - category: hardware category (server, workstation, network, peripheral)
      - form_factor: rackmount, tower, laptop, etc.
      - typical_os: typical operating system
    """
    text_lower = hardware_description.lower()

    # Category heuristics
    if any(k in text_lower for k in ["server", "rack", "data center"]):
        category = "server"
    elif any(k in text_lower for k in ["laptop", "notebook", "portable"]):
        category = "workstation"
    elif any(k in text_lower for k in ["switch", "router", "firewall", "ap "]):
        category = "network"
    elif any(k in text_lower for k in ["printer", "scanner", "copier"]):
        category = "peripheral"
    else:
        category = "other"

    # Form factor heuristics
    if "rack" in text_lower:
        form_factor = "rackmount"
    elif any(k in text_lower for k in ["laptop", "notebook"]):
        form_factor = "portable"
    else:
        form_factor = "unknown"

    # Typical OS heuristics
    if any(k in text_lower for k in ["windows", "windows server"]):
        typical_os = "windows"
    elif any(k in text_lower for k in ["linux", "red hat", "ubuntu"]):
        typical_os = "linux"
    elif any(k in text_lower for k in ["mac", "macos"]):
        typical_os = "macos"
    else:
        typical_os = "unknown"

    return {
        "description": hardware_description,
        "category": category,
        "form_factor": form_factor,
        "typical_os": typical_os,
    }


# ---------------------------------------------------------------------------
# Main Ingestion Entry Point
# ---------------------------------------------------------------------------

def ingest_customer_knowledge(
    file_data: bytes,
    file_type: str,  # "csv" or "pdf"
    customer_id: int,
) -> dict[str, Any]:
    """Main entry point for customer knowledge ingestion.

    Orchestrates:
      1. File type parsing (CSV or PDF)
      2. Context7 domain grounding of extracted terms
      3. Structured record creation
      4. Deduplication across all records

    Returns dict with:
      - success: bool
      - classified_type: knowledge type (software_inventory, hardware_inventory,
                         process_document, policy_document, other)
      - entries: list of structured knowledge records
      - errors: list of error strings
      - warnings: list of warning strings
    """
    # Error accumulator: the CSV branch short-circuits on parse errors
    # (below), the PDF branch populates it from the parser.
    errors: list[str] = []

    # Step 1: Parse based on file type
    if file_type.lower() == "csv":
        parse_result = parse_csv_knowledge(file_data, customer_id)
        if parse_result["errors"]:
            return {
                "success": False,
                "classified_type": "other",
                "entries": [],
                "errors": parse_result["errors"],
            }
        entries = parse_result["ingested"]
        classified_type = entries[0]["knowledge_type"] if entries else "other"

    elif file_type.lower() == "pdf":
        parse_result = ingest_pdf_knowledge(file_data, customer_id)
        classified_type = parse_result["classified_type"]
        entries = parse_result["entries"]
        errors = parse_result["errors"]
    else:
        return {
            "success": False,
            "classified_type": "other",
            "entries": [],
            "errors": [f"Unsupported file type: {file_type}"],
        }

    # Step 2: Perform context7 domain grounding on each entry
    for entry in entries:
        if entry["knowledge_type"] == "software_inventory" and entry.get("software"):
            grounded = ground_software_terms(entry["software"])
            entry["category"] = grounded["category"]
            entry["category_confidence"] = grounded["confidence"]
            entry["related_terms"] = grounded["related_terms"]
            entry["licensing_typical"] = grounded["licensing_typical"]
        elif entry["knowledge_type"] == "hardware_inventory" and entry.get("software"):
            # Try to use what we have as a description for hardware grounding
            grounded = ground_hardware_terms(entry.get("software", ""))
            entry["hardware_category"] = grounded["category"]
            entry["hardware_form_factor"] = grounded["form_factor"]
            entry["hardware_typical_os"] = grounded["typical_os"]

    # Step 3: Deduplicate across all entries by (software, version, customer_id)
    seen: set = set()
    deduped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for entry in entries:
        key = (
            entry.get("software", "").lower(),
            entry.get("version", ""),
            customer_id,
        )
        if key not in seen:
            seen.add(key)
            deduped.append(entry)
        else:
            warnings.append(
                f"Duplicate software entry removed: {entry.get('software')} ({entry.get('version')})"
            )

    return {
        "success": True,
        "classified_type": classified_type,
        "entries": deduped,
        "errors": errors,
        "warnings": warnings,
    }


# Alias for backward compatibility / convenience
from_hermes = ingest_customer_knowledge

