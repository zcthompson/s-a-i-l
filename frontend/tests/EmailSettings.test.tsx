/**
 * Component tests for the Application Settings "Email notifications" card
 * (EL-05/06 frontend slice) inside Notifications & ticketing.
 *
 * Pins: card placement + verbatim copy; loaded config populates every
 * field; env-only password status line (no password input); Configured /
 * Not configured status; PUT payload of exactly the six editable fields;
 * verbatim 422 detail; Test Connection success/failure lines; reset to
 * baseline; card hidden outside the notifications category.
 *
 * Assertions use plain DOM properties (repo convention — no jest-dom
 * matchers). Mocking follows vi.hoisted + vi.mock factory, as in
 * DocumentProcessingSettings.test.tsx.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { IntegrationSettings } from '../src/components/IntegrationSettings';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState(null, '', '#');
});

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getInferenceConfig: vi.fn(),
    updateInferenceConfig: vi.fn(),
    getDoclingConfig: vi.fn(),
    updateDoclingConfig: vi.fn(),
    getDocumentProcessingConfig: vi.fn(),
    updateDocumentProcessingConfig: vi.fn(),
    getLdapSettings: vi.fn(),
    updateLdapSettings: vi.fn(),
    testLdapConnection: vi.fn(),
    getIntegrationConfig: vi.fn(),
    updateIntegrationConfig: vi.fn(),
    deleteConfigEntry: vi.fn(),
    integrationStatus: vi.fn(),
    sendSlack: vi.fn(),
    sendTeams: vi.fn(),
    getEmailConfig: vi.fn(),
    updateEmailConfig: vi.fn(),
    testEmailConnection: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
}));

const EMAIL_FULL = {
  enabled: true,
  smtp_host: 'smtp.example.com',
  smtp_port: 465,
  smtp_username: 'mailer',
  smtp_security: 'ssl',
  from_address: 'sail@example.com',
  password_configured: true,
};

const EMAIL_DEFAULT = {
  enabled: false,
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_security: 'starttls',
  from_address: '',
  password_configured: false,
};

function mount(email: Record<string, unknown> = EMAIL_FULL, openNotifications = true) {
  apiMock.getInferenceConfig.mockResolvedValue({ ai_endpoint: '', ai_model: '', ssl_verify: 'full', ssl_ca_bundle: null });
  apiMock.getDoclingConfig.mockResolvedValue({ server_url: '', timeout_seconds: 600, ssl_verify: 'full', ssl_ca_bundle: null });
  apiMock.getDocumentProcessingConfig.mockResolvedValue({ provider: 'docling', azure_endpoint: '', azure_timeout_seconds: 600, azure_ssl_verify: 'full', azure_ssl_ca_bundle: null, api_key_configured: false });
  apiMock.getLdapSettings.mockResolvedValue({ enabled: false });
  apiMock.getIntegrationConfig.mockResolvedValue({});
  apiMock.integrationStatus.mockResolvedValue({ slack: false, teams: false, jira: false });
  apiMock.getEmailConfig.mockResolvedValue(email);
  const view = render(<IntegrationSettings />);
  if (openNotifications) fireEvent.click(screen.getByRole('link', { name: 'Notifications & ticketing' }));
  return view;
}

const field = <T extends HTMLElement = HTMLInputElement>(id: string) => document.getElementById(id) as T;
const card = () => document.getElementById('settings-email-card') as HTMLElement;

async function loaded() {
  await waitFor(() => expect(card().textContent).toContain('Saved configuration loaded'));
}

function statusLine() {
  const strong = Array.from(card().querySelectorAll('.settings-integration-status strong')).find((s) => s.textContent === 'Email configuration')!;
  return strong.nextElementSibling!.textContent;
}

function button(name: string) {
  return screen.getByRole('button', { name }) as HTMLButtonElement;
}

describe('Application Settings — Email notifications card (EL-05/06)', () => {
  it('renders as the first card inside the notifications section with heading and intro', async () => {
    mount();
    await loaded();
    const section = document.getElementById('settings-notifications') as HTMLElement;
    expect(section.hidden).toBe(false);
    expect(section.contains(card())).toBe(true);
    expect(section.querySelector('h2')!.textContent).toContain('Notifications & ticketing');
    const firstH4 = section.querySelector('h4')!;
    expect(firstH4.textContent).toBe('Email notifications');
    expect(card().contains(firstH4)).toBe(true);
    expect(card().textContent).toContain('Send application notifications by email through your SMTP server.');
    expect(field('settings-email-help').textContent).toBe('The SMTP password is set in the environment (SAIL_EMAIL_SMTP_PASSWORD) and is never stored in the application. Saving requires a host and a From address; enabling sends email for new in-app notifications.');
    // Precedes the Slack block.
    const slack = Array.from(section.querySelectorAll('h4')).find((h) => h.textContent?.includes('Slack Integration'))!;
    expect(card().compareDocumentPosition(slack) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('populates every field from the loaded config', async () => {
    mount();
    await loaded();
    expect(field('settings-email-enabled').checked).toBe(true);
    expect(field('settings-email-smtp-host').value).toBe('smtp.example.com');
    expect(field('settings-email-smtp-port').value).toBe('465');
    expect(field('settings-email-smtp-username').value).toBe('mailer');
    expect(field<HTMLSelectElement>('settings-email-smtp-security').value).toBe('ssl');
    expect(field('settings-email-from-address').value).toBe('sail@example.com');
    const options = Array.from(field<HTMLSelectElement>('settings-email-smtp-security').options).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ['starttls', 'STARTTLS (port 587)'],
      ['ssl', 'Implicit TLS / SSL (port 465)'],
      ['none', 'No TLS (not recommended)'],
    ]);
  });

  it('shows the env-only password line and never a password input', async () => {
    mount();
    await loaded();
    expect(field('settings-email-password-line').textContent).toBe('SMTP password: set in .env (SAIL_EMAIL_SMTP_PASSWORD) — configured');
    expect(card().querySelector('input[type="password"]')).toBeNull();
    cleanup();
    mount(EMAIL_DEFAULT);
    await loaded();
    expect(field('settings-email-password-line').textContent).toBe('SMTP password: set in .env (SAIL_EMAIL_SMTP_PASSWORD) — not configured');
  });

  it('reports Configured only when enabled with host and From address', async () => {
    mount();
    await loaded();
    expect(statusLine()).toBe('Configured · Not tested in this session');
    fireEvent.change(field('settings-email-smtp-host'), { target: { value: '' } });
    expect(statusLine()).toBe('Not configured · Not tested in this session');
  });

  it('saves exactly the six editable fields and shows the saved values', async () => {
    mount(EMAIL_DEFAULT);
    await loaded();
    const response = { ...EMAIL_FULL, smtp_host: 'mail.corp.example', smtp_port: 2525 };
    apiMock.updateEmailConfig.mockResolvedValue(response);
    fireEvent.click(field('settings-email-enabled'));
    fireEvent.change(field('settings-email-smtp-host'), { target: { value: 'mail.corp.example' } });
    fireEvent.change(field('settings-email-smtp-port'), { target: { value: '2525' } });
    fireEvent.change(field('settings-email-smtp-username'), { target: { value: 'mailer' } });
    fireEvent.change(field('settings-email-smtp-security'), { target: { value: 'ssl' } });
    fireEvent.change(field('settings-email-from-address'), { target: { value: 'sail@example.com' } });
    expect(card().textContent).toContain('Unsaved changes');
    fireEvent.click(button('Save Email Settings'));
    await waitFor(() => expect(card().textContent).toContain('Settings saved successfully'));
    expect(apiMock.updateEmailConfig).toHaveBeenCalledTimes(1);
    const payload = apiMock.updateEmailConfig.mock.calls[0][0];
    expect(payload).toEqual({
      enabled: true,
      smtp_host: 'mail.corp.example',
      smtp_port: 2525,
      smtp_username: 'mailer',
      smtp_security: 'ssl',
      from_address: 'sail@example.com',
    });
    expect('password_configured' in payload).toBe(false);
    expect(field('settings-email-smtp-host').value).toBe('mail.corp.example');
    expect(field('settings-email-smtp-port').value).toBe('2525');
    expect(field('settings-email-password-line').textContent).toContain('— configured');
    expect(button('Reset email changes').disabled).toBe(true);
  });

  it('shows the verbatim 422 detail on save failure', async () => {
    mount();
    await loaded();
    apiMock.updateEmailConfig.mockRejectedValue(new Error('from_address must be a valid email address'));
    fireEvent.click(button('Save Email Settings'));
    const alert = await waitFor(() => {
      const el = document.getElementById('settings-email-error');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(alert.textContent?.trim()).toBe('from_address must be a valid email address');
    expect(alert.getAttribute('role')).toBe('alert');
  });

  it('Test Connection shows success and verbatim failure lines', async () => {
    mount();
    await loaded();
    apiMock.testEmailConnection.mockResolvedValueOnce({ ok: true, latency_ms: 123, error: null });
    fireEvent.click(button('Test email connection'));
    await waitFor(() => expect(statusLine()).toBe('Configured · ✓ Test email sent to your own address'));
    expect(apiMock.testEmailConnection).toHaveBeenCalledTimes(1);

    apiMock.testEmailConnection.mockResolvedValueOnce({ ok: false, latency_ms: 0, error: 'SMTP authentication failed' });
    fireEvent.click(button('Test email connection'));
    await waitFor(() => expect(statusLine()).toBe('Configured · ✗ SMTP authentication failed'));
    expect(card().textContent).not.toContain('✓ Test email sent to your own address');
  });

  it('Reset returns the form to the baseline values', async () => {
    mount();
    await loaded();
    expect(button('Reset email changes').disabled).toBe(true);
    fireEvent.change(field('settings-email-smtp-host'), { target: { value: 'other.example.com' } });
    fireEvent.change(field('settings-email-smtp-port'), { target: { value: '25' } });
    fireEvent.click(field('settings-email-enabled'));
    expect(button('Reset email changes').disabled).toBe(false);
    fireEvent.click(button('Reset email changes'));
    expect(field('settings-email-smtp-host').value).toBe('smtp.example.com');
    expect(field('settings-email-smtp-port').value).toBe('465');
    expect(field('settings-email-enabled').checked).toBe(true);
    expect(card().textContent).toContain('Saved configuration loaded');
  });

  it('is hidden when another category is active', async () => {
    mount(EMAIL_FULL, false);
    await loaded();
    const section = document.getElementById('settings-notifications') as HTMLElement;
    expect(section.hidden).toBe(true);
    expect(card().closest('[hidden]')).toBe(section);
    fireEvent.click(screen.getByRole('link', { name: 'Notifications & ticketing' }));
    expect(section.hidden).toBe(false);
    fireEvent.click(screen.getByRole('link', { name: 'Sign-in & directory' }));
    expect(section.hidden).toBe(true);
  });
});
