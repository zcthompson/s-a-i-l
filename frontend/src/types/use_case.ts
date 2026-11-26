import type { PipelineAmountCoverage, PortfolioRenewal, PortfolioRenewalRow } from './intelligence_import';

export interface UseCase {
  id: number;
  title: string;
  description?: string;
  customer_id?: number;
  customer_name?: string;
  department_id?: number;
  department?: string;
  status: 'draft' | 'active' | 'completed' | 'archived';
  goals?: string[];
  challenges?: string[];
  pain_points?: string[];
  impact_category?: string;
  impact_description?: string;
  estimated_savings?: number;
  estimated_revenue?: number;
  timeline_estimate?: string;
  // Technology tracking fields (Phase 1 enhancement)
  tech_stack?: Record<string, unknown>;
  devices?: Record<string, unknown>;
  software?: Record<string, unknown>;
  vendor?: string;
  scores?: Record<string, unknown>;
  overall_score?: number;
  scored_at?: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
  updated_by?: string;
  assessment_id?: number;
  assessment_name?: string;
  /** Part 13 WS5 (R5/R8): the use case's round type ('ai' default incl.
   *  legacy no-round; 'generic' → AI scoring surfaces are gated). */
  assessment_type?: 'ai' | 'generic';
}

export interface UseCaseCreate {
  title: string;
  description?: string;
  customer_id?: number;
  department_id?: number;
  department?: string;
  // Technology tracking fields (Phase 1 enhancement)
  tech_stack?: Record<string, unknown>;
  devices?: Record<string, unknown>;
  software?: Record<string, unknown>;
  vendor?: string;
  // Mirrors the backend UseCaseCreate.status (backend/schemas/use_case.py) —
  // the wire contract accepts it; the WP23-era type just omitted it.
  status?: string;
  goals?: string[];
  challenges?: string[];
  pain_points?: string[];
  impact_category?: string;
  impact_description?: string;
  estimated_savings?: number;
  estimated_revenue?: number;
  timeline_estimate?: string;
}

export interface UseCaseUpdate {
  title?: string;
  description?: string;
  department?: string;
  status?: string;
  goals?: string[];
  challenges?: string[];
  pain_points?: string[];
  impact_category?: string;
  impact_description?: string;
  estimated_savings?: number;
  estimated_revenue?: number;
  timeline_estimate?: string;
  // Technology tracking fields (Phase 1 enhancement) — optional on update
  tech_stack?: Record<string, unknown>;
  devices?: Record<string, unknown>;
  software?: Record<string, unknown>;
  vendor?: string;
}

export interface DimensionScore {
  name: string;
  score: number;
  weight: number;
  description: string;
}

export interface ScoringResponse {
  // NOTE: no use_case_id — the backend ScoringResponse schema has no such
  // field; the id lives on the envelope's use_case (ScoredUseCaseResponse).
  dimension_scores: DimensionScore[];
  overall_score: number;
  reasoning: string;
  scored_at: string;
  recommendations?: string[];
}

export interface ScoredUseCaseResponse {
  use_case: UseCase;
  scores: ScoringResponse;
}

export interface StatsResponse {
  total_use_cases: number;
  scored_use_cases: number;
  average_score: number;
  by_status: Record<string, number>;
  by_department: Record<string, {
    count: number;
    avg_score: number;
    total_impact: number;
  }>;
  top_use_cases: Array<{
    id: number;
    title: string;
    overall_score: number;
    department: string;
    status: string;
  }>;
  impact_summary: {
    total_savings: number;
    total_revenue: number;
    total_impact: number;
  };
}

export interface ScoreTrend {
  date: string;
  count: number;
  avg_score: number;
  max_score: number;
  min_score: number;
}

export interface TemplateInfo {
  name: string;
  default_department: string;
  default_goals: string[];
  default_challenges: string[];
  default_pain_points: string[];
  // WP19 additive keys (present for every template in backend/templates.py)
  id?: string;
  icon?: string;
  description?: string;
  default_title?: string;
  impact_category?: string;
  impact_description?: string;
  timeline?: string;
}

/** GET /customers/verticals/ — the canonical vertical list + the 4 seed
 *  departments per vertical (WP19). */
export interface VerticalsResponse {
  verticals: string[];
  departments_by_vertical: Record<string, string[]>;
}

/** POST /customers/{name}/assessments/from-template/ result (WP19). */
export interface BootstrapResult {
  assessment_id: number;
  assessment_name: string;
  departments: Array<{ name: string; created: boolean }>;
  use_cases: Array<{ id: number; title: string; department: string | null }>;
  /** WP21 — example use cases pre-seeded into vertical departments left empty by the per-goal seeding. */
  preseeded: Array<{ id: number; title: string; department: string | null }>;
  count: number;
}

export interface TemplateListResponse {
  templates: Record<string, TemplateInfo>;
  count: number;
}

export interface TemplateResponse extends TemplateInfo {
  id: string;
}

export interface BulkScoreResult {
  success_count: number;
  error_count: number;
  results: Array<{
    use_case: UseCase;
    scores: ScoringResponse;
  }>;
  errors: Array<{
    use_case_id: number;
    error: string;
  }>;
}

// ── Impact Matrix ──────────────────────────────────────────────────────────

export interface ImpactMatrixPoint {
  id: number;
  title: string;
  department: string;
  overall_score: number;
  total_impact: number;
  effort_level: number;
  effort_label: string;
  impact_category: string;
  status: string;
}

export interface ImpactMatrixResponse {
  points: ImpactMatrixPoint[];
  quadrants: Record<string, string[]>;
}

// ── Department Comparison ──────────────────────────────────────────────────

export interface DeptDimensionAvg {
  dimension: string;
  avg_score: number;
  count: number;
  min_score: number;
  max_score: number;
}

export interface DeptComparisonEntry {
  department: string;
  use_case_count: number;
  avg_overall: number;
  dimension_avgs: DeptDimensionAvg[];
}

export interface DeptComparisonResponse {
  departments: DeptComparisonEntry[];
  dimensions: string[];
}

// ── Collaboration / Comments ──────────────────────────────────────────────

export interface Comment {
  id: number;
  use_case_id: number;
  user_name: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface CommentCreate {
  use_case_id: number;
  user_name: string;
  content: string;
}

// ── Notifications ──────────────────────────────────────────────────────

export interface NotificationItem {
  id: number;
  user_name: string;
  type: string;
  message: string;
  customer_id?: number | null;
  read: boolean;
  created_at: string;
}

// ── Analytics ────────────────────────────────────────────────────────────

export interface TrendPrediction {
  use_case_id?: number;
  use_case_title: string;
  current_score: number;
  /** Forecast horizon in days requested for this prediction. */
  days: number;
  /** Predicted score at the requested horizon. */
  predicted_score: number;
  /** predicted_score - current_score. */
  score_change: number;
  trend: 'improving' | 'stable' | 'declining';
  /** Legacy alias of predicted_score (kept for compatibility). */
  predicted_score_30d: number;
  slope: number;
  data_points: number;
  /** 0–1 confidence fraction (multiply by 100 for percent). */
  confidence: number;
}

export interface DepartmentTrend {
  department: string;
  use_case_count: number;
  avg_score: number;
  total_impact: number;
}

// ── Contract hygiene (WP3): dimension definitions, departments, access ──

/** A scoring dimension definition as served by GET /scoring/dimensions/
 *  (name + weight only — NOT a scored dimension). */
export interface DimensionInfo {
  name: string;
  weight: number;
}

/** A department (backend DepartmentResponse). */
export interface Department {
  id: number;
  name: string;
  customer_id: number;
  created_at: string | null;
  use_case_count: number;
}

/** One entry of GET /customers/me/customers/ — the caller's access to a
 *  customer with its junction role (admins: implicit owner, id=0). */
export interface MyCustomerAccess {
  customer_id: number;
  customer_name: string;
  description: string | null;
  role: string;
  id: number;
  granted_by: number | null;
  granted_at: string | null;
}

/** GET /global-admin/summary — the high-level dashboard summary. */
export interface GlobalAdminSummary {
  total_customers: number;
  total_use_cases: number;
  average_score: number;
  total_impact: number;
  customers_count: number;
  top_customers: FullCustomerSummary[];
}

/** GET/PUT /admin/config/inference — the effective inference config. */
export interface InferenceConfigResponse {
  ai_endpoint: string;
  ai_model: string;
  api_key: string | null;
  temperature: number;
  max_tokens: number;
  timeout: number;
  enabled: boolean;
}

// ── Score Drill-Down ──────────────────────────────────────────────────────

export interface ScoreHistoryPoint {
  timestamp: string;
  overall_score: number;
}

export interface DimensionDetail {
  name: string;
  score: number;
  weight: number;
  weighted_score: number;
  description: string;
}

export interface DrillDownResponse {
  id: number;
  title: string;
  department: string;
  status: string;
  overall_score: number;
  dimension_details: DimensionDetail[];
  score_history: ScoreHistoryPoint[];
  reasoning: string;
  recommendations: string[];
  business_impact: {
    savings: number;
    revenue: number;
    total: number;
  };
  timeline_estimate: string;
  scored_at: string;
}

// ── Authentication ────────────────────────────────────────────────────────────

export interface LoginResponse {
  username: string;
  email: string;
  display_name: string;
  token: string;
  department: string;
  is_admin: boolean;
}

export interface RegisterResponse {
  id: number;
  username: string;
  email: string;
  display_name: string;
  department: string;
  created_at: string;
  is_active: number;
  approved: number;
}

export interface UserResponse {
  id: number;
  username: string;
  /** Nullable: name-only pending owners (prod-seed) have no email until filled in. */
  email: string | null;
  display_name: string | null;
  department: string | null;
  role: string;
  sales_role: 'rep' | 'inside_sales' | 'sales_manager' | 'sales_ops' | 'auditor' | 'sales_admin' | null;
  is_admin: number;
  approved: number;
  created_at: string;
  is_active: number;
  /** 0.2.0 federated identity: 'local' | 'ldap'. */
  auth_provider: string;
}

// ── Customer Sales Team (admin correction surface) ──────────────────────────

export interface SalesTeamUser {
  user_id: number;
  name: string;
  auto_linked: boolean;
  link_reason: string | null;
}

export interface CustomerSalesTeam {
  customer_id: number;
  primary_rep: { user_id: number | null; name: string | null; sales_role: string | null } | null;
  manager: SalesTeamUser | null;
  inside_sales: SalesTeamUser[];
  sales_ops: SalesTeamUser[];
}

export interface CustomerSalesTeamUpdate {
  primary_rep_user_id: number | null;
  manager_user_id: number | null;
  inside_sales_user_ids: number[];
  sales_ops_user_ids: number[];
}

// ── Account memberships + ownership review queue (RBAC directive) ─────────

export type MembershipRole = 'primary_owner' | 'co_owner' | 'sales_ops' | 'inside_sales';

export interface AccountMembership {
  user_id: number;
  username: string;
  name: string;
  role: MembershipRole;
  section_grants: Record<string, string> | null;
  source: string;
  expires_at: string | null;
}

export interface OwnershipReviewItem {
  customer_id: number;
  name: string;
  current_owner: string | null;
  current_owner_user_id: number | null;
  placeholder: boolean;
}

// ── Customer Model ──────────────────────────────────────────────────────────

export interface Customer {
  id: number;
  name: string;
  description: string | null;
  vertical: string | null;
  branch?: string | null;
  sales_area?: string | null;
  primary_subsidiary?: string | null;
  primary_rep?: string | null;
  rep_sales_role?: string | null;
  manager_name?: string | null;
  inside_sales?: Array<{ name: string; branch?: string | null }>;
  sales_ops?: Array<{ name: string }>;
  created_at: string;
  updated_at: string;
  user_count?: number;
  use_case_count?: number;
  departments: string[];
  total_impact?: number;
  /** Part 14 — alias tags (raw strings, sorted). */
  aliases?: string[];
}

/** Part 14 — GET/POST /customers/{name}/aliases/ row. */
export interface CustomerAlias {
  id: number;
  alias: string;
  created_by: string | null;
  created_at: string | null;
}

export interface CustomerCreate {
  name: string;
  description?: string;
  vertical?: string;
}

/** GET /customers/{name}/stats/ — per-customer aggregate stats. The route
 *  re-shapes the service output; this models the WIRE shape (audit P1 —
 *  the old interface modeled the service shape, not the wire shape). */
export interface CustomerStats {
  customer_name: string;
  customer_description: string | null;
  total_use_cases: number;
  scored_use_cases: number;
  unscored_use_cases: number;
  average_score: number;
  total_savings: number;
  total_revenue: number;
  total_impact: number;
  departments: number;
  by_department: Record<string, {
    count: number;
    avg_score: number;
    total_savings: number;
    total_revenue: number;
  }>;
  status_breakdown: Record<string, number>;
  recent_activity: Array<{
    id: number;
    title: string;
    created_at: string | null;
    status: string;
    score: number | null;
  }>;
}

/** One customer summary row. total_impact/user_count are present on the
 *  global-stats path (get_global_stats); the user-scoped path
 *  (get_user_stats) omits them. */
export interface CustomerSummary {
  customer_id: number;
  customer_name: string;
  use_case_count: number;
  total_impact?: number;
  user_count?: number;
}

/** Customer summary row from get_global_stats — always complete. */
export interface FullCustomerSummary extends CustomerSummary {
  total_impact: number;
  user_count: number;
  average_score: number | null;
  total_scored: number;
}

export interface GlobalStats {
  total_customers: number;
  total_use_cases: number;
  total_scored: number;
  average_score: number;
  total_savings: number;
  total_revenue: number;
  total_impact: number;
  customers: CustomerSummary[];
}

/** GET /account-impact/portfolio/ — the single account-impact source for the
 *  global surfaces (money is customer_benefit/estimated; never a use-case
 *  savings+revenue headline). `value: null` means "Not quantified". */
export type AccountImpactCoverage = 'quantified' | 'partial' | 'not_quantified';

export interface PortfolioAccountImpact {
  customer_count: number;
  as_of: string;
  calculation_version: string;
  coverage: AccountImpactCoverage;
  scope?: string;
  total_impact: {
    value: number | null;
    perspective: string;
    realization_basis: string;
    currency: string | null;
  };
  rollup: { quantified: number; partial: number; not_quantified: number };
  customers: Array<{
    customer_id: number;
    customer_name: string;
    coverage: AccountImpactCoverage;
    total_impact: number | null;
    /** H2 display metadata (additive; not part of the calculation). */
    vertical?: string | null;
    branch?: string | null;
    sales_area?: string | null;
    primary_subsidiary?: string | null;
    primary_rep?: string | null;
    can_score?: boolean;
    can_manage_customer?: boolean;
    /** Per-account partner pipeline (unweighted, source-labelled USD). */
    pipeline?: {
      acv: number | null;
      tcv: number | null;
      coverage: PipelineAmountCoverage;
    };
    /** H3: vendor-reported renewal attention for the account (additive). */
    renewals?: PortfolioRenewalRow;
  }>;
  /** H3: scoped renewal rollup (additive; separate from impact and pipeline). */
  renewals?: PortfolioRenewal;
  /** Portfolio partner pipeline — separate from total_impact, never combined. */
  pipeline?: PortfolioPipeline;
}

export interface PortfolioPipelineAmount {
  total: number | null;
  lines: number;
  accounts_quantified: number;
  accounts_partial: number;
  accounts_recorded_zero: number;
  accounts_all_unknown: number;
  accounts_no_data: number;
}

export interface PortfolioPipeline {
  calculation_version: string;
  as_of: string;
  acv: PortfolioPipelineAmount;
  tcv: PortfolioPipelineAmount;
  note: string;
}

/** GET /global-admin/stats — the aggregate above merged with the global
 *  user counts (UserService.get_user_stats); customer rows come from
 *  get_global_stats and are always complete. */
export interface GlobalAdminStats extends GlobalStats {
  total_users: number;
  active_users: number;
  pending_users: number;
  admin_count?: number;
  role_breakdown?: { admin: number; user: number; auditor: number };
  score_bands: { high: number; mid: number; low: number; unscored: number };
  customers: FullCustomerSummary[];
}

// ── Customer-User Junction ──────────────────────────────────────────────────

export interface CustomerUser {
  id: number;
  customer_id: number;
  customer_name: string | null;
  user_id: number;
  username: string | null;
  role: string;  // owner | member | auditor
  granted_by: number | null;
  granted_at: string | null;
}

export interface CustomerUserResponse {
  users: CustomerUser[];
}

export interface AccessCheckResponse {
  has_access: boolean;
  permission_level: string;
  customer_name: string;
  customer_id: number;
}

export interface MyCustomersResponse {
  customers: CustomerUser[];
}

export interface UserStatsResponse {
  total_use_cases: number;
  total_scored: number;
  average_score: number;
  total_savings: number;
  total_revenue: number;
  customers: Array<{
    customer_id: number;
    customer_name: string;
    use_case_count: number;
  }>;
}

// ── Projections ─────────────────────────────────────────────────────

export interface ProjectionAxis {
  current: number;
  projected: number;
  projected_30d?: number; // legacy payloads (pre-rename)
  trajectory: 'improving' | 'stable' | 'declining';
}

export interface Projection {
  customer_name: string;
  generated_at: string;
  horizon?: string; // '30-60d' | '3-6m' | '6-12m'
  horizon_label?: string; // '30–60 days' | '3–6 months' | '6–12 months'
  speed: ProjectionAxis;
  value: ProjectionAxis;
  key_factors: string[];
  recommendations: string[];
  confidence: number;
  model_used?: boolean;
}

// ── Assessment Rounds ─────────────────────────────────────────────

export interface CustomerAssessment {
  id: number;
  customer_id: number;
  name: string;
  status: 'active' | 'archived';
  created_by: string | null;
  created_at: string | null;
  archived_at: string | null;
  use_case_count: number;
  // Part 13 WS5 (R1/R2/R6): round type + optional "why". Generic rounds
  // carry no AI scoring / forecasts / readiness insight / template bootstrap.
  assessment_type: AssessmentType;
  purpose: string | null;
}

export type AssessmentType = 'ai' | 'generic';

// ── Model-Generated Predictions ───────────────────────────────────

export interface AIPrediction {
  id: number;
  use_case_id: number;
  use_case_title: string | null;
  customer_id: number | null;
  horizon_days: number;
  predicted_score: number;
  score_change: number | null;
  trend: 'improving' | 'stable' | 'declining' | string;
  confidence: number | null;
  reasoning: string | null;
  model: string | null;
  created_by: string | null;
  created_at: string | null;
}

// ── Readiness Insight (WP33 — persisted, LLM-generated per-customer) ──────
// GET/POST /api/analytics/readiness-insight/ — the backend implements exactly
// this shape (see the WP33 API contract).

export interface ReadinessInsightData {
  summary: string;
  strengths: string[];
  weaknesses: string[];
  priorities: string[];
  context: {
    total_use_cases: number;
    included_count: number;
    missing_count: number;
    missing_reasons: { unscored: number; not_completed: number };
    missing_titles: string[];
    average_score: number | null;
    weakest_dimension: { name: string; average: number } | null;
    strongest_dimension: { name: string; average: number } | null;
    departments: Array<{ name: string; use_case_count: number; avg_score: number; total_impact: number }>;
    top_use_cases: Array<{ title: string; score: number; department: string }>;
    lowest_use_cases: Array<{ title: string; score: number; department: string }>;
    total_impact: number;
    generated_at: string;
  };
  missing_note: string | null;
  model_used: boolean;
}

export interface ReadinessInsight {
  id: number;
  customer_id: number;
  customer_name: string;
  insight_data: ReadinessInsightData;
  data_fingerprint: string;
  model: string | null;
  generated_by: string | null;
  status: 'completed' | 'failed';
  generated_at: string | null;
}

export interface ReadinessInsightState {
  total: number;
  included: number;
  unscored: number;
  not_completed: number;
  missing_count: number;
  ready: boolean;
  all_scored: boolean;
  all_completed: boolean;
}

export interface ReadinessInsightResponse {
  insight: ReadinessInsight | null;
  state: ReadinessInsightState;
  stale: boolean;
}
