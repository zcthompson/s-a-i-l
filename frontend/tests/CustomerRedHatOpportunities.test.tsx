import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CustomerRedHatOpportunities } from '../src/components/CustomerRedHatOpportunities';

const { getReport } = vi.hoisted(() => ({ getReport: vi.fn() }));
vi.mock('../src/lib/api', () => ({ api: { getRedHatOpportunityReport: getReport } }));
afterEach(() => cleanup());

it('labels the source representative and keeps indicators as observations', async () => {
  getReport.mockResolvedValue({ import: { import_id: 1, file_name: 'synthetic.xlsx', created_at: '2026-11-04' },
    matched_account: 'Synthetic Account', opportunities: [
      { type: 'openshift_virtualization', title: 'OpenShift Virtualization', vendors: ['VMware'],
        redhat_representatives: ['Synthetic RH Rep'] },
      { type: 'ansible_network_automation', title: 'Ansible Network Automation', vendors: ['Cisco', 'F5'],
        redhat_representatives: [] },
    ] });
  render(<CustomerRedHatOpportunities customerId={9} />);
  expect((await screen.findByText('Synthetic RH Rep')).textContent).toContain('Red Hat representative: Synthetic RH Rep');
  expect(screen.getByText(/not confirmed deals/)).toBeTruthy();
  expect(screen.getByText('OpenShift Virtualization')).toBeTruthy();
  expect(screen.getByText('Ansible Network Automation')).toBeTruthy();
  expect(screen.getAllByText(/Matched account:/)).toHaveLength(2);
  expect(screen.getByText(/Cisco, F5/)).toBeTruthy();
  expect(screen.queryByText(/Source account|Workbook row/)).toBeNull();
});
