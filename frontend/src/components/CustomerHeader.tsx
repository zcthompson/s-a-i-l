/**
 * compact persistent CustomerHeader.
 *
 * One unified header for the customer workspace: the name as the primary
 * title, the description as subdued supporting text, and account metadata
 * (vertical, departments-as-count with a full-list popover, your role on
 * the account, active-assessment compact status) integrated in a single
 * row instead of multiple disconnected rows. Customer administration
 * (Edit / Departments / Team / Remove) lives in an overflow settings menu —
 * never alongside primary workflows; a single
 * customer-level "+ Add" control exposes the create actions.
 *
 * The full-width active-assessment banner becomes a compact
 * status element with a single contextual action.
 */
import { ActionMenu } from './workspacePrimitives';

export interface ActiveRoundInfo {
  name: string;
  total: number;
  scored: number;
  generic?: boolean;
  completed?: number;
}

export type AddTarget = 'use-case' | 'technology' | 'sales-note' | 'knowledge' | 'assessment' | 'contact' | 'activity' | 'task' | 'deal';
export type SettingsTarget = 'edit' | 'departments' | 'team' | 'remove';

interface CustomerHeaderProps {
  name: string;
  description?: string;
  vertical?: string | null;
  branch?: string | null;
  primaryRep?: string | null;
  insideSales?: string[];
  salesOps?: string[];
  managerName?: string | null;
  /** The signed-in user's role on THIS customer (owner/member/auditor/none). */
  userRole: string;
  canManageCustomer: boolean;
  /** Owner / sales admin / admin — opens Edit Customer for the Aliases
   *  section even without metadata rights (the sales admin case). */
  canManageAliases?: boolean;
  canAddUseCase: boolean;
  /** Compact active-assessment status; null when none. */
  activeRound?: ActiveRoundInfo | null;
  createPermissions?: Record<string, boolean>;
  onManageRounds?: () => void;
  onAdd?: (target: AddTarget) => void;
  onOpenSettings?: (target: SettingsTarget) => void;
}

const ROLE_TEXT: Record<string, string> = {
  owner: 'Owner',
  member: 'Member',
  auditor: 'Auditor (read-only)',
  none: 'No access',
};

/** Semantic role chip colors (no emoji): owner=healthy, member=accent,
 * auditor=neutral, none=attention. */
function roleChipStyle(role: string): React.CSSProperties {
  const soft =
    role === 'owner' ? 'var(--status-positive-soft)'
    : role === 'member' ? 'var(--brand-50)'
    : role === 'auditor' ? 'var(--neutral-100)'
    : 'var(--status-warning-soft)';
  const fg =
    role === 'owner' ? 'var(--status-positive)'
    : role === 'member' ? 'var(--brand-700)'
    : role === 'auditor' ? 'var(--neutral-500)'
    : 'var(--status-warning)';
  return {
    padding: '2px 10px', borderRadius: 'var(--radius-pill)', background: soft,
    color: fg, fontSize: '0.75rem', fontWeight: 600, whiteSpace: 'nowrap',
  };
}

export function CustomerHeader({
  name, description, vertical, branch, primaryRep, insideSales = [], salesOps = [], managerName,
  userRole, canManageCustomer, canManageAliases = false, canAddUseCase, activeRound,
  onManageRounds, onAdd, onOpenSettings, createPermissions = {},
}: CustomerHeaderProps) {
  const canCreate = canAddUseCase && userRole !== 'auditor' && userRole !== 'none';
  const hasAccountMetadata = Boolean(branch || primaryRep || managerName || insideSales.length || salesOps.length);

  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          {/* Primary title + vertical. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '6px' }}>
            <h1 style={{ margin: 0, fontSize: '1.6rem', color: 'var(--ink)', fontWeight: 700, overflowWrap: 'anywhere', minWidth: 0 }}>{name}</h1>
            {vertical && (
              <span style={{ fontSize: '0.7rem', fontWeight: 600, padding: '3px 10px', background: 'var(--brand-50)', color: 'var(--brand-700)', borderRadius: 'var(--radius-pill)' }}>
                {vertical}
              </span>
            )}
          </div>
          {hasAccountMetadata && (
            <div style={{ display: 'flex', gap: '12px', fontSize: '0.82rem', color: 'var(--neutral-500)', alignItems: 'center', flexWrap: 'wrap', marginBottom: '8px' }}>
              {branch && (
                <span style={{ padding: '2px 9px', borderRadius: 'var(--radius-pill)', background: 'var(--neutral-100)', color: 'var(--neutral-700)', fontWeight: 600 }}>
                  {branch}
                </span>
              )}
              <span>Primary rep: <strong>{primaryRep || 'Unassigned'}</strong></span>
              {managerName && <span>Manager: <strong>{managerName}</strong></span>}
              {insideSales.length > 0 && (
                <span>Inside sales: <strong>{insideSales.join(' · ')}</strong></span>
              )}
              {salesOps.length > 0 && (
                <span>Sales ops: <strong>{salesOps.join(' · ')}</strong></span>
              )}
            </div>
          )}
          {description && (
            <p style={{ margin: '0 0 8px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>{description}</p>
          )}
          {/* Access and active-assessment status stay visible without account
              use-case or department counts in this header. */}
          <div style={{ display: 'flex', gap: '14px', fontSize: '0.82rem', color: 'var(--neutral-500)', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={roleChipStyle(userRole)}>You: {ROLE_TEXT[userRole] || 'Member'}</span>
            {/* Compact active-assessment status element:
                replaces the full-width banner. */}
            {activeRound && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: 'var(--brand-50)', color: 'var(--brand-700)', borderRadius: 'var(--radius-pill)', padding: '2px 4px 2px 10px', fontSize: '0.78rem', fontWeight: 500 }}>
                <span>
                  Active assessment: <strong>{activeRound.name}</strong> · {activeRound.generic ? `${activeRound.completed ?? 0}/${activeRound.total} use cases completed` : `${activeRound.scored}/${activeRound.total} AI use cases scored`}
                </span>
                {onManageRounds && (
                  <button
                    role="button"
                    aria-label="Manage assessment rounds"
                    onClick={onManageRounds}
                    style={{ padding: '2px 10px', margin: 0, background: 'var(--brand-700)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-pill)', cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600 }}
                  >
                    Manage
                  </button>
                )}
              </span>
            )}
          </div>
        </div>
        {/* Single + Add control + account-management overflow.
             Destructive actions live in the settings menu only. */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {onAdd && (
            <ActionMenu
              label="+ Add"
              variant="primary"
              ariaLabel="Add to customer"
              items={[
                ...(['contact', 'activity', 'task', 'deal'] as const).map(target => ({ label: target[0].toUpperCase() + target.slice(1), onClick: () => onAdd(target), disabled: !createPermissions[target] })),
                { label: 'Use Case', onClick: () => onAdd('use-case'), disabled: !canCreate, divider: true },
                { label: 'Technology', onClick: () => onAdd('technology'), disabled: !canCreate },
                { label: 'Sales Note', onClick: () => onAdd('sales-note'), disabled: !canCreate },
                { label: 'Knowledge Source', onClick: () => onAdd('knowledge'), disabled: !canCreate },
                { label: 'Assessment', onClick: () => onAdd('assessment'), disabled: !canCreate },
              ]}
            />
          )}
          {onOpenSettings && (
            <ActionMenu
              label="More"
              ariaLabel="Customer settings"
              align="end"
              title="Customer settings"
              items={[
                { label: 'Team', onClick: () => onOpenSettings('team'), divider: true },
                ...(canManageCustomer
                  ? [
                      { label: 'Edit Customer', onClick: () => onOpenSettings('edit') },
                      { label: 'Departments', onClick: () => onOpenSettings('departments') },
                      { label: 'Remove Customer', onClick: () => onOpenSettings('remove'), destructive: true },
                    ]
                  : canManageAliases
                    // Sales admin: Edit Customer opens for the Aliases only.
                    ? [{ label: 'Edit Customer', onClick: () => onOpenSettings('edit') }]
                    : []),
              ]}
            />
          )}
        </div>
      </div>
    </div>
  );
}
