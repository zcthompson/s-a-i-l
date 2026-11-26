import { DealPromotion } from './DealPromotion';
import { useDealSources } from '../lib/useDealSources';
/**
 * CHANGELOG 0.1.0 U5 (data: U1) — Opportunities & Attention panel.
 *
 * Synthesizes actionable information across Technology Inventory, Sales
 * Notes, Customer Knowledge, Assessments, and Use Cases (directive 27) as
 * typed cards — Observed Gap, Growth Opportunity, Lifecycle Risk,
 * Discovery Needed, Recommended Follow-up (directive 28). Every card shows
 * WHY it exists via its supporting evidence (directive 29) and the panel
 * carries the Generate Sales Evaluation call to action near the summary
 * (directive 30) so the Sales workflow is one click away.
 *
 * Data comes from the deterministic account-workspace endpoint
 * (services/customer_intelligence.py::get_account_workspace) — nothing is
 * invented client-side. Severity colors are semantic (directive 43):
 * red = critical risk, amber = attention, neutral = informational.
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { PromoteTaskButton } from './PromoteTaskButton';
import { AccountWorkspace, OpportunityType, WorkspaceOpportunity } from '../types/sail';

const TYPE_LABEL: Record<OpportunityType, string> = {
  observed_gap: 'Observed Gap',
  growth_opportunity: 'Growth Opportunity',
  lifecycle_risk: 'Lifecycle Risk',
  discovery_needed: 'Discovery Needed',
  follow_up: 'Recommended Follow-up',
  renewal_attention: 'Renewal Attention',
  contact_coverage: 'Contact Coverage',
  eol_attention: 'End-of-support Attention',
};

const SOURCE_LABEL: Record<string, string> = {
  technology: 'Technology Inventory',
  sales_evaluation: 'Sales Evaluation',
  use_case: 'Use Case',
  sales_note: 'Sales Note',
  sales_notes: 'Sales Notes',
  customer_knowledge: 'Customer Knowledge',
  partner_pipeline: 'Partner Pipeline',
  customer_contacts: 'Customer Contacts',
};

function severityStyle(sev: WorkspaceOpportunity['severity']): { background: string; color: string; border: string } {
  if (sev === 'high') return { background: 'var(--status-negative-soft)', color: 'var(--status-negative)', border: '1px solid var(--status-negative)' };
  if (sev === 'medium') return { background: 'var(--status-warning-soft)', color: 'var(--status-warning)', border: '1px solid var(--status-warning)' };
  return { background: 'var(--neutral-100)', color: 'var(--neutral-500)', border: '1px solid var(--neutral-200)' };
}

interface OpportunitiesPanelProps {
  allowDeals?: boolean;
  onOpenDeal?: (id: number) => void;
  customerId: number;
  /** Navigate to the Sales Evaluations workspace (the CTA target). */
  onExplore?: () => void;
  /** Write gate for follow-up promotion (same source as ContactsPanel; backend 403 is authoritative). */
  userRole?: string;
}

// The contact_coverage card id embeds the customer id: contact-coverage-{cid}.
function coverageSourceId(op: WorkspaceOpportunity): number | null {
  const m = /^contact-coverage-(\d+)$/.exec(op.id);
  return m ? Number(m[1]) : null;
}

function promotionSource(op: WorkspaceOpportunity): { type: 'renewal_attention' | 'contact_coverage' | 'eol_attention'; id: number } | null {
  if (op.type === 'eol_attention' && op.evidence.source_id != null) return { type: 'eol_attention', id: op.evidence.source_id };
  if (op.type === 'renewal_attention' && op.evidence.source_id != null) return { type: 'renewal_attention', id: op.evidence.source_id };
  if (op.type === 'contact_coverage') {
    const id = coverageSourceId(op);
    if (id != null) return { type: 'contact_coverage', id };
  }
  return null;
}

function OpportunityCard({ op, customerId, onExplore, canPromote, allowDeals, onOpenDeal, sources }: { allowDeals: boolean; onOpenDeal?: (id: number) => void; sources: Record<string, number>; op: WorkspaceOpportunity; customerId: number; onExplore?: () => void; canPromote: boolean }) {
  const sev = severityStyle(op.severity);
  const promo = canPromote ? promotionSource(op) : null;
  return (
    <div style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '14px', boxShadow: 'var(--shadow-card)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
        <span style={{ padding: '2px 10px', borderRadius: 'var(--radius-pill)', background: sev.background, color: sev.color, fontSize: '0.72rem', fontWeight: 600, border: sev.border }}>
          {op.severity.toUpperCase()}
        </span>
        <span style={{ fontSize: '0.72rem', color: 'var(--brand-700)', fontWeight: 600, background: 'var(--brand-50)', padding: '2px 10px', borderRadius: 'var(--radius-pill)' }}>
          {TYPE_LABEL[op.type]}
        </span>
      </div>
      <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--ink)', marginBottom: '4px' }}>{op.title}</div>
      {op.detail && (
        <div style={{ fontSize: '0.85rem', color: 'var(--neutral-600)', marginBottom: '8px', lineHeight: 1.5 }}>{op.detail}</div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>
          <span title="Why this opportunity exists — the supporting record it was derived from (deterministic aggregation, not model output)">Why:</span>{' '}
          {op.evidence.source_name || SOURCE_LABEL[op.evidence.source] || op.evidence.source}
          {' · '}{SOURCE_LABEL[op.evidence.source] || op.evidence.source}
        </span>
        {promo && (
          <PromoteTaskButton customerId={customerId} sourceType={promo.type} sourceId={promo.id} label={op.title} />
        )}
        {onExplore && (
          <button
            role="button"
            aria-label={`Explore opportunity ${op.title}`}
            onClick={onExplore}
            style={{ padding: '4px 12px', margin: 0, background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.78rem', fontWeight: 600 }}
          >
            Explore
          </button>
        )}
      </div>
      <DealPromotion customerId={customerId} attentionId={op.id} vendor={op.evidence.source === 'partner_pipeline' && op.evidence.source_id && op.evidence.source_name ? { import_id: op.evidence.source_id, opportunity_number: op.evidence.source_name } : undefined} linkedDealId={sources[op.evidence.source === 'partner_pipeline' ? `vendor:${op.evidence.source_name}` : `attention:${op.id}`]} allowed={allowDeals} onOpen={onOpenDeal} />
    </div>
  );
}

export function OpportunitiesPanel({ customerId, onExplore, userRole, allowDeals = false, onOpenDeal }: OpportunitiesPanelProps) {
  const sources = useDealSources(customerId);
  const [workspace, setWorkspace] = useState<AccountWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setWorkspace(null);
    setError(null);
    api
      .getAccountWorkspace(customerId)
      .then((w) => { if (alive) setWorkspace(w); })
      .catch((e: any) => { if (alive) setError(e?.message || 'Failed to load opportunities'); });
    return () => { alive = false; };
  }, [customerId]);

  if (error) {
    return (
      <div style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', fontSize: '0.85rem', marginBottom: '24px' }}>
        {error}
      </div>
    );
  }
  // Guard against a non-object response (a stub resolving [] must not crash
  // the Overview — same convention as AccountOverview/IntelligencePanels).
  if (!workspace || !Array.isArray(workspace.opportunities)) return null;
  const ops = workspace.opportunities;
  if (ops.length === 0) return null;

  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '12px', flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--neutral-700)' }}>
          Attention
          <span style={{ marginLeft: '8px', fontSize: '0.75rem', color: 'var(--neutral-500)', fontWeight: 500 }}>({ops.length})</span>
        </h3>
        {onExplore && (
          <button
            role="button"
            aria-label="Generate a persona-driven sales evaluation for this customer"
            onClick={onExplore}
            style={{ padding: '8px 16px', margin: 0, background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
          >
            Generate Sales Evaluation
          </button>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
        {ops.map((op) => (
          <OpportunityCard sources={sources} allowDeals={allowDeals} onOpenDeal={onOpenDeal} key={`${customerId}-${op.id}`} op={op} customerId={customerId} onExplore={onExplore} canPromote={userRole !== 'auditor' && userRole !== 'none'} />
        ))}
      </div>
    </div>
  );
}
