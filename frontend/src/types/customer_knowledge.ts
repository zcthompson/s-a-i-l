/** Customer Knowledge contract (PLAN.md part 43 / CHANGELOG 0.1.1).
 *
 * `processing_status` is the UI's source of truth (UPLOADED / PROCESSING /
 * READY / FAILED); `processed` is the legacy boolean kept for backward
 * compatibility (mirrors READY). The list/detail wire carries
 * `normalized_content_present` (bool) rather than the full Markdown blob —
 * the content is fetched via the dedicated content endpoint.
 */
export type KnowledgeProcessingStatus =
  | 'UPLOADED'
  | 'PROCESSING'
  | 'READY'
  | 'FAILED';

/** LLM enrichment lifecycle (CHANGELOG 0.1.2 items 2, 16):
 *  tracked separately from Docling processing_status. */
export type KnowledgeEnrichmentStatus =
  | 'NOT_RUN'
  | 'ENRICHING'
  | 'ENRICHED'
  | 'FAILED'
  | 'SKIPPED';

/** Knowledge category slugs (item 1). The user's choice is authoritative;
 *  the LLM may suggest one when absent. */
export const KNOWLEDGE_CATEGORIES: { value: string; label: string }[] = [
  { value: 'general_customer_information', label: 'General Customer Information' },
  { value: 'business_strategy_goals', label: 'Business Strategy / Goals' },
  { value: 'business_challenges_pain_points', label: 'Business Challenges / Pain Points' },
  { value: 'technology_infrastructure', label: 'Technology / Infrastructure' },
  { value: 'applications_platforms', label: 'Applications / Platforms' },
  { value: 'security_compliance', label: 'Security / Compliance' },
  { value: 'operations_processes', label: 'Operations / Processes' },
  { value: 'projects_initiatives', label: 'Projects / Initiatives' },
  { value: 'products_services', label: 'Products / Services' },
  { value: 'vendors_partners', label: 'Vendors / Partners' },
  { value: 'organizational_stakeholder_information', label: 'Organizational / Stakeholder Information' },
  { value: 'use_cases', label: 'Use Cases' },
  { value: 'opportunities', label: 'Opportunities' },
  { value: 'assessments_discovery', label: 'Assessments / Discovery' },
  { value: 'commercial_procurement', label: 'Commercial / Procurement' },
  { value: 'meeting_notes_customer_communications', label: 'Meeting Notes / Customer Communications' },
  { value: 'architecture_technical_documentation', label: 'Architecture / Technical Documentation' },
  { value: 'other', label: 'Other' },
];

export function knowledgeCategoryLabel(value?: string | null): string {
  if (!value) return 'Uncategorized';
  return KNOWLEDGE_CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

export interface KnowledgeEnrichmentItem {
  id: number;
  customer_id: number;
  source_knowledge_id: number;
  legacy_rvtools_source?: boolean;
  kind: string;
  name: string;
  description?: string | null;
  /** explicit (stated) | derived (inferred) | suggested (candidate) — item 6 */
  provenance: string;
  confidence?: number | null;
  evidence?: string | null;
  source_reference?: string | null;
  /** created | linked | skipped | failed — application to domain objects (item 5) */
  applied_status?: string | null;
  applied_object_type?: string | null;
  applied_object_id?: number | null;
  enrichment_model?: string | null;
  extracted_at?: string | null;
}

export interface CustomerKnowledgeEntry {
  id: number;
  customer_id: number;
  knowledge_type: string;
  file_name: string;
  original_filename?: string;
  original_content_type?: string;
  original_storage_path?: string;
  uploaded_at: string;
  processed: boolean;
  extracted_text?: string;
  ingestion_status?: string;
  classification?: string;
  category?: string;
  /** Knowledge category slug (item 1), or null when unclassified. */
  knowledge_category?: string | null;
  // Docling normalization layer
  normalized_format?: string;
  normalized_content_present?: boolean;
  processing_status: KnowledgeProcessingStatus;
  processing_error?: string | null;
  processing_error_kind?: string | null;
  processor?: string | null;
  processor_version?: string | null;
  processing_time_seconds?: number | null;
  processed_at?: string | null;
  // LLM enrichment layer (item 16: separate from processing_status)
  enrichment_status?: KnowledgeEnrichmentStatus;
  enrichment_error?: string | null;
  enrichment_error_kind?: string | null;
  enrichment_model?: string | null;
  enrichment_time_seconds?: number | null;
  enriched_at?: string | null;
}

export interface KnowledgeUploadResponse {
  success: boolean;
  knowledge_id: number;
  classified_type: string;
  entries_count: number;
  warnings: string[];
  processing_status: KnowledgeProcessingStatus;
}

export interface KnowledgeContentResponse {
  id: number;
  customer_id: number;
  file_name: string;
  normalized_format: string;
  normalized_content: string;
  processor?: string | null;
  processing_status: KnowledgeProcessingStatus;
  processed_at?: string | null;
}
