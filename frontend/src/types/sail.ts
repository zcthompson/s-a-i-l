// S-A-I-L (Sales Analytics and Intelligence Launchpad) domain types — Technology Inventory,
// Sales Notes, Customer Intelligence Overview, Sales Personas, Evaluation Preview.
// These mirror the backend Pydantic schemas (backend/schemas/*) and the
// deterministic services (backend/services/customer_intelligence.py,
// sales_personas.py, evaluation_engine.py). v2 item 43: clear TypeScript
// contracts for the new S-A-I-L surfaces.

export type VerificationState = "verified" | "inferred" | "unverified";

// ── Technology Inventory (S-A-I-L P2) ──────────────────────────────────────────
export interface CustomerTechnology {
  id: number;
  customer_id: number;
  name: string;
  vendor: string | null;
  category: string;
  version_edition: string | null;
  deployment_model: string | null;
  quantity: number | null;
  footprint: string | null;
  purpose: string | null;
  lifecycle_state: string | null;
  support_state: string | null;
  business_criticality: string | null;
  source: string | null;
  date_observed: string | null; // ISO date
  end_of_support_date: string | null;
  eol_source: string | null;
  verification_state: VerificationState;
  confidence: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerTechnologyCreate {
  name: string;
  category: string;
  vendor?: string | null;
  version_edition?: string | null;
  deployment_model?: string | null;
  quantity?: number | null;
  footprint?: string | null;
  purpose?: string | null;
  lifecycle_state?: string | null;
  support_state?: string | null;
  business_criticality?: string | null;
  source?: string | null;
  date_observed?: string | null;
  end_of_support_date?: string | null;
  eol_source?: string | null;
  verification_state?: VerificationState;
  confidence?: number | null;
  notes?: string | null;
}

// ── Sales Notes (S-A-I-L P3) ───────────────────────────────────────────────────
export interface SalesNote {
  id: number;
  customer_id: number;
  author: string | null;
  source: string | null;
  note_date: string | null; // ISO date
  category: string;
  title: string;
  content: string;
  verification_state: VerificationState;
  related_technology_ids: number[];
  related_use_case_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface SalesNoteCreate {
  category: string;
  title: string;
  content: string;
  author?: string | null;
  source?: string | null;
  note_date?: string | null;
  verification_state?: VerificationState;
  related_technology_ids?: number[];
  related_use_case_ids?: number[];
}

// ── Third-Party Professional Services (S-A-I-L P2) ────────────────────────────
export interface ThirdPartyService {
  id: number;
  customer_id: number;
  vendor_name: string;
  service_category: string;
  engagement_status: string;
  description: string;
  sow_reference: string | null;
  contract_reference: string | null;
  started_on: string | null; // ISO date
  ended_on: string | null; // ISO date
  billing_model: string | null;
  fee_amount: number | null; // monthly / 30-day figure
  verification_state: VerificationState;
  notes: string | null;
  created_by: string | null;
  related_use_case_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface ThirdPartyServiceCreate {
  vendor_name: string;
  service_category: string;
  description: string;
  engagement_status?: string;
  sow_reference?: string | null;
  contract_reference?: string | null;
  started_on?: string | null;
  ended_on?: string | null;
  billing_model?: string | null;
  fee_amount?: number | null;
  verification_state?: VerificationState;
  notes?: string | null;
  use_case_ids?: number[];
}

export interface ThirdPartyServiceUpdate {
  vendor_name?: string;
  service_category?: string;
  description?: string;
  engagement_status?: string;
  sow_reference?: string | null;
  contract_reference?: string | null;
  started_on?: string | null;
  ended_on?: string | null;
  billing_model?: string | null;
  fee_amount?: number | null;
  verification_state?: VerificationState;
  notes?: string | null;
  use_case_ids?: number[];
}

export interface ThirdPartyServiceDocument {
  id: number;
  service_id: number;
  customer_id: number;
  document_type: string;
  file_name: string;
  title: string | null;
  uploaded_by: string | null;
  created_at: string;
}

// ── Customer Intelligence Overview (S-A-I-L P4) ───────────────────────────────
export interface CriticalTechAtRisk {
  id: number;
  name: string;
  vendor: string | null;
  category: string;
  lifecycle_state: string | null;
  support_state: string | null;
  business_criticality: string | null;
  verification_state: VerificationState;
}

export interface CustomerIntelligenceOverview {
  customer_id: number;
  generated_at: string;
  method: string; // "deterministic_aggregation"
  technology_inventory: {
    total: number;
    by_category: Record<string, number>;
    by_verification: Record<string, number>;
    by_lifecycle: Record<string, number>;
    by_criticality: Record<string, number>;
    eol_count: number;
    average_confidence: number | null;
    critical_tech_at_risk: CriticalTechAtRisk[];
    critical_tech_at_risk_count: number;
    unverified_pct: number | null;
  };
  sales_notes: {
    total: number;
    by_category: Record<string, number>;
    by_verification: Record<string, number>;
    latest_note_date: string | null;
    days_since_latest_note: number | null;
    stale_after_days: number;
    notes_stale: boolean;
  };
  use_cases: {
    total: number;
    by_status: Record<string, number>;
    scored_count: number;
    scored_ratio: number | null;
    average_overall_score: number | null;
  };
  customer_knowledge: {
    total: number;
    by_type: Record<string, number>;
    by_ingestion_status: Record<string, number>;
    unprocessed_count: number;
  };
  indicators: {
    eol_tech_count: number;
    critical_tech_at_risk_count: number;
    unverified_tech_pct: number | null;
    notes_stale: boolean;
    days_since_latest_note: number | null;
    scored_use_case_ratio: number | null;
    knowledge_unprocessed_count: number;
    [key: string]: number | null | boolean;
  };
}

// ── Sales Personas (S-A-I-L P5) ───────────────────────────────────────────────
export interface SalesPersona {
  id: string;
  label: string;
  description: string;
  technical_depth: "low" | "medium" | "high";
  business_framing: string;
  risk_framing: string;
  focus_dimensions: string[];
  concerns: string[];
  question_base: string[];
  priority_angles: string[];
  next_action_angles: string[];
}

// ── Evaluation Preview (S-A-I-L P5) ───────────────────────────────────────────
export interface SalesEvaluationPreview {
  customer: { id: number; name: string; vertical: string | null };
  persona: SalesPersona | { id: null; label: string } & Record<string, unknown>;
  available_intelligence: {
    technology_items: number;
    sales_notes: number;
    knowledge_entries: number;
    use_cases: { total: number; scored: number };
    eol_tech_count: number;
    critical_tech_at_risk_count: number;
    notes_stale: boolean;
  };
  generation_intent: string;
  // The 10 persona-tailored sections, each { label, content } (+ extra keys).
  sections: Record<string, { label: string; content: unknown; [key: string]: unknown }>;
  discovery_gaps: Array<{ area: string; gap: string; action: string }>;
  source_context: Record<string, unknown>;
}

// ── Controlled vocabularies ─────────────────────────────────────────────────
// Mirror the backend single-source-of-truth lists (backend/models/
// customer_technology.py + sales_note.py). Used for deterministic form
// selects / filter options; the backend still validates and returns 422 on
// an unknown value, so any drift is caught at the API boundary.

export const TECH_CATEGORIES = [
  "software", "hardware", "infrastructure", "cloud_platform", "virtualization",
  "networking", "storage", "security", "data_platform", "ai_technology",
  "operating_system", "management_tool", "automation_tool", "other",
] as const;

export const DEPLOYMENT_MODELS = [
  "on_premise", "private_cloud", "public_cloud", "hybrid", "saas",
  "virtual_machine", "container", "bare_metal", "unknown",
] as const;

export const LIFECYCLE_STATES = [
  "current", "previous_generation", "eol_announced", "eol", "unknown",
] as const;

export const SUPPORT_STATES = [
  "under_support", "support_expiring", "no_support", "unknown",
] as const;

export const BUSINESS_CRITICALITIES = ["critical", "high", "medium", "low"] as const;

export const VERIFICATION_STATES: VerificationState[] = ["verified", "inferred", "unverified"];

export const SALES_NOTE_CATEGORIES = [
  "discovery", "account_observation", "meeting", "technical_discussion", "risk",
  "initiative", "objection", "competitive", "follow_up", "opportunity", "other",
] as const;

export const SERVICE_CATEGORIES = [
  "technical", "virtualization", "automation", "cloud", "infrastructure",
  "network", "security", "data_analytics", "application_development",
  "managed_services",
] as const;

export const ENGAGEMENT_STATUSES = [
  "planned", "active", "completed", "cancelled", "pending",
] as const;

export const BILLING_MODELS = ["tm", "fixed"] as const;

export const DOCUMENT_TYPES = [
  "po", "sow", "contract", "change_order", "invoice", "statement", "other",
] as const;

const titleCaseVocabulary = (value: string): string =>
  value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export const formatServiceCategory = (value: string): string => {
  if (value === "data_analytics") return "Data / Analytics";
  return titleCaseVocabulary(value);
};

export const formatEngagementStatus = (value: string): string => titleCaseVocabulary(value);

export const formatBillingModel = (value: string | null): string => {
  if (value === "tm") return "T&M";
  if (value === "fixed") return "Fixed";
  return "—";
};

export const formatDocumentType = (value: string): string => {
  if (value === "po") return "PO";
  if (value === "sow") return "SOW";
  return titleCaseVocabulary(value);
};

// ── Account Workspace (CHANGELOG 0.1.0 U1) ──────────────────────────────────────────
// GET /api/customers/{id}/intelligence/workspace/ — deterministic account
// workspace context: four actionable summaries, consolidated Business Impact,
// latest-evaluation reference, and typed, evidence-backed opportunities
// (backend: services/customer_intelligence.py::get_account_workspace).
export interface WorkspaceKeyCount {
  key: string;
  count: number;
}

export interface WorkspaceTechAtRisk {
  id: number;
  name: string;
  vendor: string | null;
  category: string | null;
  lifecycle_state: string | null;
  support_state: string | null;
  business_criticality: string | null;
  verification_state: string | null;
  purpose: string | null;
}

export interface WorkspaceTechnologyLandscape {
  total: number;
  key_vendors: WorkspaceKeyCount[];
  key_categories: WorkspaceKeyCount[];
  eol_count: number;
  unsupported_count: number;
  at_risk_count: number;
  critical_tech_at_risk: WorkspaceTechAtRisk[];
  unverified_pct: number | null;
  important_gaps: string[];
}

export interface WorkspaceKnowledge {
  total: number;
  sources: Record<string, number>;
  by_type: Record<string, number>;
  latest_uploaded: string | null;
  days_since_latest: number | null;
  recently_added_count: number;
  unprocessed_count: number;
}

export interface WorkspaceNoteBrief {
  id: number;
  title: string;
  note_date: string | null;
  category: string;
  verification_state: string;
}

export interface WorkspaceSalesActivity {
  total_notes: number;
  last_interaction: WorkspaceNoteBrief | null;
  days_since_last_interaction: number | null;
  notes_stale: boolean;
  recent: WorkspaceNoteBrief[];
  active_observations: WorkspaceNoteBrief[];
}

export interface WorkspaceAssessmentSummary {
  active_assessment: {
    id: number;
    name: string;
    status: string;
    total_count: number;
    scored_count: number;
    progress_pct: number | null;
  } | null;
  average_score: number | null;
  top_use_cases: Array<{ id: number; title: string; overall_score: number; status: string }>;
  unscored_count: number;
  total_count: number;
  scored_count: number;
}

export interface WorkspaceBusinessImpact {
  total_savings: number;
  total_revenue: number;
  total_impact: number;
  contributing_use_cases: number;
}

export interface WorkspaceEvaluationRef {
  id: number;
  evaluation_name: string;
  persona: string | null;
  created_at: string | null;
  risk_factors: Array<Record<string, unknown>>;
  growth_opportunities: Array<Record<string, unknown>>;
  discovery_gaps: Array<{ area: string; gap: string; action: string }>;
}

export type OpportunityType =
  | "lifecycle_risk"
  | "observed_gap"
  | "growth_opportunity"
  | "discovery_needed"
  | "follow_up"
  | "renewal_attention"
  | "contact_coverage"
  | "eol_attention";

export interface WorkspaceOpportunity {
  id: string;
  type: OpportunityType;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string | null;
  evidence: { source: string; source_id: number | null; source_name: string | null };
}

export interface AccountWorkspace {
  customer_id: number;
  generated_at: string;
  method: string;
  account: {
    id: number;
    name: string | null;
    vertical: string | null;
    description: string | null;
    department_count: number;
    member_count: number;
    owner: {
      user_id: number;
      display_name: string | null;
      username: string | null;
      role: string;
    } | null;
  };
  technology_landscape: WorkspaceTechnologyLandscape;
  knowledge: WorkspaceKnowledge;
  sales_activity: WorkspaceSalesActivity;
  assessment: WorkspaceAssessmentSummary;
  business_impact: WorkspaceBusinessImpact;
  latest_evaluation: WorkspaceEvaluationRef | null;
  opportunities: WorkspaceOpportunity[];
  headline: {
    active_use_cases: number;
    business_impact: WorkspaceBusinessImpact;
    technologies_known: number;
    open_opportunities_count: number;
  };
}

// ── F3 — Customer Intelligence graph projection (constellation) ──────────
// The backend `GET /api/customers/{id}/intelligence/graph/` returns a
// visualization view model (nodes/links) over the authorized customer's
// S-A-I-L records. The frontend owns force layout / rendering / interaction;
// the backend owns authorization, relationships, provenance, and the
// deterministic classification (verified vs inferred).

export type GraphNodeKind =
  | 'customer'
  | 'domain'
  | 'technology'
  | 'use_case'
  | 'sales_note'
  | 'assessment'
  | 'assessment_generic'
  | 'sales_evaluation'
  | 'risk'
  | 'opportunity'
  | 'group'
  | 'empty';

export interface GraphNode {
  id: string;
  type: GraphNodeKind;
  label: string;
  category: string;
  entityId: number;
  entityType: string;
  importance: number | null;
  status: string | null;
  confidence: number | null;
  verified: boolean | null;
  metadata: Record<string, unknown>;
  route: string;
  /** Hierarchy (0 customer, 1 domain hub, 2 group/empty, 3 leaf). Optional: older backends omit it. */
  level?: number | null;
  parentId?: string | null;
  groupKey?: string | null;
  empty?: boolean;
}

export interface GraphLink {
  id: string;
  source: string;
  target: string;
  relationship: string;
  relationshipType: string;
  strength: number | null;
  verified: boolean | null;
  confidence: number | null;
  provenance: string | null;
}

export interface GraphLimits {
  max_per_domain: number;
  technology_total: number;
  technology_shown: number;
  use_case_total: number;
  use_case_shown: number;
  sales_note_total: number;
  sales_note_shown: number;
  dependencies_total: number;
  dependencies_shown: number;
  opportunities_total: number;
  group_limits?: Record<string, { total: number; shown: number }>;
  empty_portions?: Record<string, number>;
}

export interface CustomerIntelligenceGraph {
  customer_id: number;
  generated_at: string;
  method: string;
  customer_label: string;
  nodes: GraphNode[];
  links: GraphLink[];
  limits: GraphLimits;
}
