import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { IntegrationSettings } from '../src/components/IntegrationSettings';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getInferenceConfig: vi.fn(),
    updateInferenceConfig: vi.fn(),
    getDoclingConfig: vi.fn(),
    updateDoclingConfig: vi.fn(),
    getLdapSettings: vi.fn(),
    updateLdapSettings: vi.fn(),
    testLdapConnection: vi.fn(),
    getIntegrationConfig: vi.fn(),
    updateIntegrationConfig: vi.fn(),
    deleteConfigEntry: vi.fn(),
    integrationStatus: vi.fn(),
    sendSlack: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({ api: apiMock }));

const LDAP_SETTINGS = {
  enabled: false,
  server_uri: 'ldaps://dc01.corp:636',
  service_bind_dn: 'CN=sil-svc,OU=ServiceAccounts,DC=corp,DC=local',
  user_search_base_dn: 'OU=Users,DC=corp,DC=local',
  user_search_filter: '(sAMAccountName={username})',
  start_tls: false,
  require_tls: true,
  ssl_verify: 'full',
  ssl_ca_bundle: null,
  timeout_seconds: 12,
  email_attr: 'mail',
  display_name_attr: 'displayName',
  department_attr: 'department',
  external_id_attr: 'objectGUID',
  auto_approve: false,
  default_role: 'user',
  login_disabled: false,
  local_register_enabled: true,
};

beforeEach(() => {
  Object.values(apiMock).forEach((mock) => mock.mockReset());
  apiMock.getInferenceConfig.mockResolvedValue({
    ai_endpoint: '', ai_model: '', temperature: 0.7, max_tokens: 1500,
    timeout: 60, ssl_verify: 'full', ssl_ca_bundle: null,
  });
  apiMock.getDoclingConfig.mockResolvedValue({
    server_url: '', timeout_seconds: 600, ssl_verify: 'full', ssl_ca_bundle: null,
  });
  apiMock.getLdapSettings.mockResolvedValue(LDAP_SETTINGS);
  apiMock.getIntegrationConfig.mockResolvedValue({});
  apiMock.integrationStatus.mockResolvedValue({ slack: false, teams: false, jira: false });
});

afterEach(cleanup);

function mount() {
  const view = render(<IntegrationSettings />);
  fireEvent.click(screen.getByRole('link', { name: 'Sign-in & directory' }));
  return view;
}

describe('Directory Authentication (LDAP/AD) settings', () => {
  it('renders loaded directory fields, trust controls, safe roles, and the env-password note', async () => {
    mount();
    const server = await screen.findByLabelText('LDAP server URI') as HTMLInputElement;
    await waitFor(() => expect(server.value).toBe('ldaps://dc01.corp:636'));

    expect((screen.getByLabelText('Enable directory authentication (LDAP/AD)') as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText('LDAP service bind DN') as HTMLInputElement).value).toBe(LDAP_SETTINGS.service_bind_dn);
    expect((screen.getByLabelText('LDAP search base DN') as HTMLInputElement).value).toBe(LDAP_SETTINGS.user_search_base_dn);
    expect((screen.getByLabelText('LDAP user search filter') as HTMLInputElement).value).toBe(LDAP_SETTINGS.user_search_filter);
    expect((screen.getByLabelText('LDAP timeout seconds') as HTMLInputElement).value).toBe('12');
    expect((screen.getByLabelText('LDAP local registration enabled') as HTMLInputElement).checked).toBe(true);

    const trust = screen.getByLabelText('LDAP SSL verification mode') as HTMLSelectElement;
    const ca = screen.getByLabelText('LDAP custom CA bundle') as HTMLTextAreaElement;
    expect(trust.value).toBe('full');
    expect(ca.disabled).toBe(true);
    fireEvent.change(trust, { target: { value: 'ca' } });
    expect(ca.disabled).toBe(false);

    const role = screen.getByLabelText('LDAP default role') as HTMLSelectElement;
    expect(Array.from(role.options).map((option) => option.value)).toEqual(['user', 'auditor', 'ps_admin']);
    expect(Array.from(role.options).some((option) => option.value === 'admin')).toBe(false);
    expect(screen.getByText(/SAIL_AUTH_LDAP_SERVICE_BIND_PASSWORD/)).toBeTruthy();
  });

  it('saves the complete form payload and clears the CA bundle outside ca mode', async () => {
    apiMock.updateLdapSettings.mockResolvedValue({ ...LDAP_SETTINGS, enabled: true, server_uri: 'ldap://dc02.corp:389' });
    mount();
    const server = await screen.findByLabelText('LDAP server URI') as HTMLInputElement;
    await waitFor(() => expect(server.value).toBe(LDAP_SETTINGS.server_uri));

    fireEvent.click(screen.getByLabelText('Enable directory authentication (LDAP/AD)'));
    fireEvent.change(server, { target: { value: '  ldap://dc02.corp:389  ' } });
    fireEvent.change(screen.getByLabelText('LDAP default role'), { target: { value: 'auditor' } });
    fireEvent.change(screen.getByLabelText('LDAP timeout seconds'), { target: { value: '20' } });
    fireEvent.click(screen.getByLabelText('LDAP StartTLS'));
    fireEvent.click(screen.getByLabelText('LDAP local registration enabled'));
    fireEvent.click(screen.getByRole('button', { name: 'Save LDAP settings' }));

    await waitFor(() => expect(apiMock.updateLdapSettings).toHaveBeenCalledTimes(1));
    expect(apiMock.updateLdapSettings.mock.calls[0][0]).toEqual({
      enabled: true,
      server_uri: 'ldap://dc02.corp:389',
      service_bind_dn: LDAP_SETTINGS.service_bind_dn,
      user_search_base_dn: LDAP_SETTINGS.user_search_base_dn,
      user_search_filter: LDAP_SETTINGS.user_search_filter,
      start_tls: true,
      require_tls: true,
      ssl_verify: 'full',
      ssl_ca_bundle: '',
      timeout_seconds: 20,
      email_attr: 'mail',
      display_name_attr: 'displayName',
      department_attr: 'department',
      external_id_attr: 'objectGUID',
      auto_approve: false,
      default_role: 'auditor',
      login_disabled: false,
      local_register_enabled: false,
    });
  });

  it('surfaces save-time validation detail in the section', async () => {
    apiMock.updateLdapSettings.mockRejectedValue(new Error('user_search_filter may only parameterize {username}'));
    mount();
    await screen.findByLabelText('LDAP server URI');
    fireEvent.click(screen.getByRole('button', { name: 'Save LDAP settings' }));
    expect(await screen.findByText('user_search_filter may only parameterize {username}')).toBeTruthy();
  });

  it('disables testing until enabled and shows both success and failure results inline', async () => {
    apiMock.testLdapConnection
      .mockResolvedValueOnce({ ok: true, latency_ms: 34, user_count_sampled: 1, error: null })
      .mockResolvedValueOnce({ ok: false, latency_ms: 9, user_count_sampled: 0, error: 'Bind failed' });
    mount();
    await screen.findByLabelText('LDAP server URI');
    const testButton = screen.getByRole('button', { name: 'Test directory connection' }) as HTMLButtonElement;
    expect(testButton.disabled).toBe(true);
    expect(screen.getByText('Enable directory authentication to test the connection')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Enable directory authentication (LDAP/AD)'));
    expect(testButton.disabled).toBe(true);
    apiMock.updateLdapSettings.mockResolvedValue({ ...LDAP_SETTINGS, enabled: true });
    fireEvent.click(screen.getByRole('button', { name: 'Save LDAP settings' }));
    await waitFor(() => expect(testButton.disabled).toBe(false));
    fireEvent.click(testButton);
    expect(await screen.findByText('✓ Connected in 34 ms')).toBeTruthy();

    fireEvent.click(testButton);
    expect(await screen.findByText('✗ Bind failed')).toBeTruthy();
  });
});
