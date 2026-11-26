/**
 * promotion wiring on OpportunitiesPanel + the five new notification
 * types rendering in NotificationBell (verbatim payload; no logic change).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { OpportunitiesPanel } from '../src/components/OpportunitiesPanel';
import { NotificationBell } from '../src/components/NotificationBell';
import { NEW_NOTIFICATION_TYPES } from '../src/types/engagement';

afterEach(() => cleanup());

const { apiMock } = vi.hoisted(() => ({
  apiMock: { getAccountWorkspace: vi.fn(), promoteTask: vi.fn(), getNotifications: vi.fn(), markNotificationRead: vi.fn() },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));
vi.mock('../src/lib/auth', () => ({ getAuthUsername: () => 'rep1' }));

const card = (over: Record<string, unknown>) => ({
  severity: 'medium', detail: null, evidence: { source: 'partner_pipeline', source_id: 77, source_name: 'Deal' }, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getAccountWorkspace.mockResolvedValue({
    customer_id: 5,
    opportunities: [
      card({ id: 'renewal-attention-77', type: 'renewal_attention', title: 'Renewal soon' }),
      card({ id: 'contact-coverage-5', type: 'contact_coverage', title: 'No champion', evidence: { source: 'customer_contacts', source_id: null, source_name: null } }),
      card({ id: 'lifecycle-risk-tech-2', type: 'lifecycle_risk', title: 'EOL', evidence: { source: 'technology', source_id: 2, source_name: 'VMware' } }),
    ],
  });
  apiMock.promoteTask.mockResolvedValue({ created: true, task: {} });
});

describe('OpportunitiesPanel promotion', () => {
  it('offers promotion only on renewal_attention and contact_coverage cards, with the right source ids', async () => {
    render(<OpportunitiesPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Create follow-up task from Renewal soon'));
    await waitFor(() => expect(apiMock.promoteTask).toHaveBeenCalledWith(5, { source_type: 'renewal_attention', source_id: 77 }));
    fireEvent.click(screen.getByLabelText('Create follow-up task from No champion'));
    await waitFor(() => expect(apiMock.promoteTask).toHaveBeenCalledWith(5, { source_type: 'contact_coverage', source_id: 5 }));
    expect(screen.queryByLabelText('Create follow-up task from EOL')).toBeNull();
  });

  it('created=false renders the neutral inline status, not an error', async () => {
    apiMock.promoteTask.mockResolvedValue({ created: false, task: {} });
    render(<OpportunitiesPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Create follow-up task from Renewal soon'));
    expect((await screen.findByRole('status')).textContent).toBe('Task already exists for this source');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('auditors get no promotion buttons', async () => {
    render(<OpportunitiesPanel customerId={5} userRole="auditor" />);
    await screen.findByText('Renewal soon');
    expect(screen.queryByLabelText('Create follow-up task from Renewal soon')).toBeNull();
  });
});

describe('NotificationBell task types', () => {
  it('renders all five new task notification types verbatim', async () => {
    const rows = NEW_NOTIFICATION_TYPES.map((type, i) => ({
      id: i + 1, user_name: 'rep1', type, message: `Message for ${type}`, customer_id: 5, read: false, created_at: new Date().toISOString(),
    }));
    apiMock.getNotifications.mockResolvedValue(rows);
    render(<NotificationBell unreadCount={5} onNavigate={() => {}} />);
    fireEvent.click(screen.getByLabelText(/^Notifications, 5 unread/));
    for (const t of NEW_NOTIFICATION_TYPES) {
      expect(await screen.findByText(`Message for ${t}`)).toBeTruthy();
    }
  });
});
