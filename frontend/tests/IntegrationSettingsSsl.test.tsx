/**
 * Component tests for the Application Settings connection-trust surfaces
 * (docs/archive/PLAN_LDAP_AD_AUTH.md P0b, user direction 2026-09-14).
 *
 * Covers the two new/extended sections in IntegrationSettings:
 * - Inference: ssl_verify select (full/skip/ca) + ssl_ca_bundle textarea
 *   (enabled only in ca mode) + 422 error detail surfaced in-page.
 * - Docling (NEW — was env-only before): server_url / timeout / ssl fields,
 *   save payload, the "API key is set via environment" note, and no api_key
 *   field rendered.
 *
 * Assertions use plain DOM properties (repo convention — no jest-dom
 * matchers). Mocking follows vi.hoisted + vi.mock factory.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { IntegrationSettings } from '../src/components/IntegrationSettings';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getInferenceConfig: vi.fn(),
    updateInferenceConfig: vi.fn(),
    getDoclingConfig: vi.fn(),
    updateDoclingConfig: vi.fn(),
    getIntegrationConfig: vi.fn(),
    updateIntegrationConfig: vi.fn(),
    deleteConfigEntry: vi.fn(),
    integrationStatus: vi.fn(),
    sendSlack: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
}));

const INFER_DEFAULT = {
  ai_endpoint: 'https://api.openai.com/v1',
  ai_model: 'gpt-4o',
  api_key: null,
  temperature: 0.3,
  max_tokens: 2000,
  timeout: 60,
  enabled: true,
  ssl_verify: 'full',
  ssl_ca_bundle: null,
};

const DOCLING_DEFAULT = {
  server_url: 'http://docling.example.internal:5001',
  timeout_seconds: 600,
  ssl_verify: 'full',
  ssl_ca_bundle: null,
};

function mount(category: 'ai' | 'documents' | 'notifications' = 'ai') {
  apiMock.getInferenceConfig.mockResolvedValue(INFER_DEFAULT);
  apiMock.getDoclingConfig.mockResolvedValue(DOCLING_DEFAULT);
  apiMock.getIntegrationConfig.mockResolvedValue({});
  apiMock.integrationStatus.mockResolvedValue({ slack: false, teams: false, jira: false });
  const view = render(<IntegrationSettings />);
  fireEvent.click(screen.getByRole('link', { name: category === 'ai' ? 'AI service' : category === 'documents' ? 'Document processing' : 'Notifications & ticketing' }));
  return view;
}

describe('Application Settings — inference TLS trust fields (P0b)', () => {
  it('renders the TLS verification select with the three modes', async () => {
    mount();
    const select = (await screen.findByLabelText('Inference SSL verification mode')) as HTMLSelectElement;
    const options = Array.from(select.querySelectorAll('option')).map((o) => o.value);
    expect(options).toEqual(['full', 'skip', 'ca']);
    expect(select.value).toBe('full');
  });

  it('disables the CA bundle textarea unless mode is ca', async () => {
    mount();
    const ta = (await screen.findByLabelText('Inference custom CA bundle')) as HTMLTextAreaElement;
    expect(ta.disabled).toBe(true);
    const select = screen.getByLabelText('Inference SSL verification mode') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'ca' } });
    expect(ta.disabled).toBe(false);
  });

  it('saves inference ssl fields; bundles only in ca mode', async () => {
    apiMock.updateInferenceConfig.mockResolvedValue(INFER_DEFAULT);
    mount();
    const select = (await screen.findByLabelText('Inference SSL verification mode')) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'skip' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save AI service settings' }));
    await waitFor(() => expect(apiMock.updateInferenceConfig).toHaveBeenCalledTimes(1));
    const payload = apiMock.updateInferenceConfig.mock.calls[0][0];
    expect(payload.ssl_verify).toBe('skip');
    expect(payload.ssl_ca_bundle).toBe('');
  });

  it('surfaces a 422 detail in-page (invalid CA bundle)', async () => {
    apiMock.updateInferenceConfig.mockRejectedValue(
      new Error('ssl_verify=\'ca\' requires a CA bundle (PEM certificate(s))'),
    );
    mount();
    const select = (await screen.findByLabelText('Inference SSL verification mode')) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'ca' } });
    fireEvent.change(screen.getByLabelText('Inference custom CA bundle'), { target: { value: 'invalid PEM contents' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save AI service settings' }));
    await waitFor(() =>
      expect(screen.getByText(/requires a CA bundle/)).toBeTruthy(),
    );
  });
});

describe('Application Settings — Docling section (P0b, new)', () => {
  it('renders the Docling section with loaded values', async () => {
    mount('documents');
    const url = (await screen.findByLabelText('Docling server URL')) as HTMLInputElement;
    expect(url.value).toBe('http://docling.example.internal:5001');
    expect((screen.getByLabelText('Docling timeout seconds') as HTMLInputElement).value).toBe('600');
    expect((screen.getByLabelText('Docling SSL verification mode') as HTMLSelectElement).value).toBe('full');
    // The env-only API key note (no editable key field).
    expect(screen.getByText(/SAIL_DOCLING_API_KEY/)).toBeTruthy();
  });

  it('saves docling config with the ssl trust fields', async () => {
    apiMock.updateDoclingConfig.mockResolvedValue(DOCLING_DEFAULT);
    mount('documents');
    const url = (await screen.findByLabelText('Docling server URL')) as HTMLInputElement;
    fireEvent.change(url, { target: { value: 'https://docling.internal:5001' } });
    const select = screen.getByLabelText('Docling SSL verification mode') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'skip' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Docling settings' }));
    await waitFor(() => expect(apiMock.updateDoclingConfig).toHaveBeenCalledTimes(1));
    expect(apiMock.updateDoclingConfig.mock.calls[0][0]).toEqual({
      server_url: 'https://docling.internal:5001',
      timeout_seconds: 600,
      ssl_verify: 'skip',
      ssl_ca_bundle: '',
    });
  });

  it('surfaces a 422 invalid-PEM detail for docling', async () => {
    apiMock.updateDoclingConfig.mockRejectedValue(new Error('Invalid CA bundle: no certificate found'));
    mount('documents');
    const select = (await screen.findByLabelText('Docling SSL verification mode')) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'ca' } });
    const ta = screen.getByLabelText('Docling custom CA bundle') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'not-a-cert' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Docling settings' }));
    await waitFor(() => expect(screen.getByText(/Invalid CA bundle/)).toBeTruthy());
  });
});

describe('Integration save and test isolation', () => {
  it('saves Teams without Jira and tests only its saved endpoint', async () => {
    const sendTeams = vi.fn().mockResolvedValue(undefined);
    Object.assign(apiMock, { sendTeams });
    apiMock.sendSlack.mockClear();
    apiMock.updateIntegrationConfig.mockResolvedValue({});
    mount('notifications');
    const field = await screen.findByLabelText('Microsoft Teams webhook URL');
    fireEvent.change(field, { target: { value: 'https://example.test/teams' } });
    expect((screen.getByLabelText('Test Microsoft Teams connection') as HTMLButtonElement).disabled).toBe(true);
    apiMock.getIntegrationConfig.mockResolvedValue({ teams: { webhook_url: 'https://example.test/teams' } });
    fireEvent.click(screen.getByLabelText('Save Teams settings'));
    await waitFor(() => expect(apiMock.updateIntegrationConfig).toHaveBeenCalledWith('teams', { webhook_url: 'https://example.test/teams' }));
    await waitFor(() => expect((screen.getByLabelText('Test Microsoft Teams connection') as HTMLButtonElement).disabled).toBe(false));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(screen.getByLabelText('Test Microsoft Teams connection'));
    await waitFor(() => expect(sendTeams).toHaveBeenCalled());
    expect(apiMock.sendSlack).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it('retains an inference key after a failed save and clears saved feedback on edits', async () => {
    mount('notifications');
    const key = await screen.findByLabelText('Inference API key');
    fireEvent.change(key, { target: { value: 'synthetic-key' } });
    apiMock.updateInferenceConfig.mockRejectedValueOnce(new Error('Save unavailable'));
    fireEvent.click(screen.getByLabelText('Save AI service settings'));
    await screen.findByText('Save unavailable');
    expect((key as HTMLInputElement).value).toBe('synthetic-key');
    apiMock.updateInferenceConfig.mockResolvedValueOnce({});
    fireEvent.click(screen.getByLabelText('Save AI service settings'));
    await screen.findByText('✓ Saved');
    expect((key as HTMLInputElement).value).toBe('');
    fireEvent.change(key, { target: { value: 'new-key' } });
    expect(screen.queryByText('✓ Saved')).toBeNull();
  });
});

it('blocks integration writes after load failure', async () => {
  apiMock.getIntegrationConfig.mockRejectedValueOnce(new Error('Unavailable'));
  mount('notifications');
  await screen.findByRole('button', { name: 'Retry integration settings' });
  expect((screen.getByLabelText('Save Slack settings') as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText('Save all integration settings') as HTMLButtonElement).disabled).toBe(true);
});

it('reports partial save risk and blocks retries after a write failure', async () => {
  mount('notifications');
  const field = await screen.findByLabelText('Slack webhook URL');
  fireEvent.change(field, { target: { value: 'https://example.test/slack' } });
  apiMock.updateIntegrationConfig.mockRejectedValueOnce(new Error('Write failed'));
  fireEvent.click(screen.getByLabelText('Save Slack settings'));
  await screen.findByText(/Some changes may already be saved/);
  expect((screen.getByLabelText('Save all integration settings') as HTMLButtonElement).disabled).toBe(true);
});

it('retries only the failed service and preserves another service draft', async () => {
  apiMock.getInferenceConfig.mockRejectedValueOnce(new Error('AI offline'));
  mount('ai');
  fireEvent.click(await screen.findByRole('button', { name: 'Retry inference settings' }));
  await waitFor(() => expect((screen.getByLabelText('Save AI service settings') as HTMLButtonElement).disabled).toBe(false));
  fireEvent.change(screen.getByLabelText('Docling server URL'), { target: { value: 'https://draft.example.test' } });
  fireEvent.change(screen.getByLabelText('Inference API key'), { target: { value: 'draft-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Reset AI changes' }));
  expect((screen.getByLabelText('Inference API key') as HTMLInputElement).value).toBe('');
  expect((screen.getByLabelText('Docling server URL') as HTMLInputElement).value).toBe('https://draft.example.test');
});

it('does not let a delayed service load overwrite an editable draft', async () => {
  let resolve!: (value: typeof INFER_DEFAULT) => void;
  apiMock.getInferenceConfig.mockReturnValueOnce(new Promise(r => { resolve = r; }));
  mount('ai');
  const field = await screen.findByLabelText('Inference API key');
  expect(field.closest('fieldset')?.disabled).toBe(true);
  resolve(INFER_DEFAULT);
  await waitFor(() => expect(field.closest('fieldset')?.disabled).toBe(false));
  fireEvent.change(field, { target: { value: 'draft' } });
  expect((field as HTMLInputElement).value).toBe('draft');
});

it('recovers integration loading without reloading service drafts', async () => {
  apiMock.getIntegrationConfig.mockRejectedValueOnce(new Error('offline'));
  mount('notifications');
  await screen.findByRole('button', { name: 'Retry integration settings' });
  fireEvent.change(screen.getByLabelText('Docling server URL'), { target: { value: 'https://draft.test' } });
  fireEvent.click(screen.getByRole('button', { name: 'Retry integration settings' }));
  await waitFor(() => expect((screen.getByLabelText('Save Slack settings') as HTMLButtonElement).disabled).toBe(false));
  expect((screen.getByLabelText('Docling server URL') as HTMLInputElement).value).toBe('https://draft.test');
});

it('saving Slack preserves a Teams draft and reset restores only Teams', async () => {
  mount('notifications');
  const slack = await screen.findByLabelText('Slack webhook URL');
  await waitFor(() => expect(slack.closest('fieldset')?.disabled).toBe(false));
  const teams = screen.getByLabelText('Microsoft Teams webhook URL');
  fireEvent.change(slack, { target: { value: 'https://slack.example.test' } });
  fireEvent.change(teams, { target: { value: 'https://teams-draft.example.test' } });
  apiMock.updateIntegrationConfig.mockResolvedValue({});
  apiMock.getIntegrationConfig.mockResolvedValue({ slack: { webhook_url: 'https://slack.example.test' } });
  fireEvent.click(screen.getByLabelText('Save Slack settings'));
  await screen.findByText('Integration settings saved successfully');
  expect((teams as HTMLInputElement).value).toBe('https://teams-draft.example.test');
  fireEvent.click(screen.getByRole('button', { name: 'Reset Teams changes' }));
  expect((teams as HTMLInputElement).value).toBe('');
  expect((slack as HTMLInputElement).value).toBe('https://slack.example.test');
});

it('warns before leaving with a draft and removes the warning after reset', async () => {
  mount('documents');
  const field = await screen.findByLabelText('Docling server URL');
  await waitFor(() => expect(field.closest('fieldset')?.disabled).toBe(false));
  fireEvent.change(field, { target: { value: 'https://draft.test' } });
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Reset Docling changes' }));
  const clean = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);
});

it('category navigation retains drafts and exposes only the selected settings', async () => {
  mount();
  const key = await screen.findByLabelText('Inference API key');
  await waitFor(() => expect(key.closest('fieldset')?.disabled).toBe(false));
  fireEvent.change(key, { target: { value: 'draft-key' } });
  fireEvent.click(screen.getByRole('link', { name: 'Notifications & ticketing' }));
  expect(screen.queryByRole('button', { name: 'Save AI service settings' })).toBeNull();
  expect(screen.getByRole('link', { name: 'Notifications & ticketing' }).getAttribute('aria-current')).toBe('location');
  fireEvent.click(screen.getByRole('link', { name: 'AI service' }));
  expect((screen.getByLabelText('Inference API key') as HTMLInputElement).value).toBe('draft-key');
});

it('canceling Back retains a draft and accepting Back calls the destination', async () => {
  mount(); cleanup();
  const back = vi.fn();
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  render(<IntegrationSettings onBack={back} />);
  fireEvent.click(screen.getByRole('link', { name: 'AI service' }));
  const key = await screen.findByLabelText('Inference API key');
  await waitFor(() => expect(key.closest('fieldset')?.disabled).toBe(false));
  fireEvent.change(key, { target: { value: 'draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Back to Dashboard' }));
  expect(back).not.toHaveBeenCalled();
  expect((key as HTMLInputElement).value).toBe('draft');
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Back to Dashboard' }));
  expect(back).toHaveBeenCalledOnce();
  confirm.mockRestore();
});

it('keeps numeric blanks as drafts, opens Advanced and focuses validation before saving', async () => {
  mount();
  const timeout = await screen.findByLabelText('Timeout (seconds)', { selector: '#settings-ai-timeout' }) as HTMLInputElement;
  await waitFor(() => expect(timeout.closest('fieldset')?.disabled).toBe(false));
  fireEvent.change(timeout, { target: { value: '' } });
  expect(timeout.value).toBe('');
  const advanced = timeout.closest('details')!;
  advanced.open = false;
  const previous = apiMock.updateInferenceConfig.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Save AI service settings' }));
  expect(apiMock.updateInferenceConfig.mock.calls.length).toBe(previous);
  expect(advanced.open).toBe(true);
  expect(document.activeElement).toBe(timeout);
  expect(timeout.getAttribute('aria-invalid')).toBe('true');
  expect(timeout.getAttribute('aria-errormessage')).toBe('settings-inference-error');
  expect(timeout.getAttribute('aria-describedby')).toBe('settings-ai-timeout-hint');
  fireEvent.click(screen.getByRole('button', { name: 'Reset AI changes' }));
  expect(timeout.value).toBe('60');
  expect(timeout.hasAttribute('aria-invalid')).toBe(false);
});

it('requires a custom CA before attempting a save and associates the error with the field', async () => {
  mount();
  const mode = await screen.findByLabelText('Inference SSL verification mode');
  fireEvent.change(mode, { target: { value: 'ca' } });
  const previous = apiMock.updateInferenceConfig.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Save AI service settings' }));
  const certificate = screen.getByLabelText('Inference custom CA bundle');
  expect(document.activeElement).toBe(certificate);
  expect(certificate.getAttribute('aria-invalid')).toBe('true');
  expect(apiMock.updateInferenceConfig.mock.calls.length).toBe(previous);
});

it('gives visible integration labels explicit associations and purpose-based names', async () => {
  mount('notifications');
  const webhook = await screen.findByRole('textbox', { name: 'Slack webhook URL' }) as HTMLInputElement;
  expect(webhook.labels?.[0]?.htmlFor).toBe(webhook.id);
  expect(webhook.getAttribute('aria-describedby')).toBe('settings-slack-webhook-url-hint');
  expect(screen.queryByRole('textbox', { name: 'https://hooks.slack.com/services/...' })).toBeNull();
});

it('restores the effective saved Docling URL when a blank override is skipped by the server', async () => {
  mount('documents');
  const url = await screen.findByLabelText('Docling server URL') as HTMLInputElement;
  await waitFor(() => expect(url.closest('fieldset')?.disabled).toBe(false));
  apiMock.updateDoclingConfig.mockResolvedValue(DOCLING_DEFAULT);
  fireEvent.change(url, { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save Docling settings' }));
  await waitFor(() => expect(url.value).toBe(DOCLING_DEFAULT.server_url));
});

it('reports an existing AI key without echoing its value into the replacement field', async () => {
  apiMock.getInferenceConfig.mockResolvedValueOnce({ ...INFER_DEFAULT, api_key: 'synthetic-existing-key' });
  mount();
  expect(await screen.findByText('A key is configured on the server.')).toBeTruthy();
  expect((screen.getByLabelText('Inference API key') as HTMLInputElement).value).toBe('');
  expect(document.body.textContent).not.toContain('synthetic-existing-key');
});

it('keeps section guidance visible while limiting per-field speech to a concise hint', async () => {
  mount();
  const model = await screen.findByLabelText('Model');
  const hintId = model.getAttribute('aria-describedby')!;
  expect(document.getElementById(hintId)?.textContent).toBe('Optional. Blank keeps the current model.');
  expect(document.getElementById('settings-inference-help')?.textContent).toContain('Saved overrides');
  expect(model.closest('fieldset')?.getAttribute('aria-describedby')).toContain('settings-inference-help');
});

it('restores keyboard focus to the save action after an asynchronous save', async () => {
  let finish!: (value: typeof INFER_DEFAULT) => void;
  apiMock.updateInferenceConfig.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  mount();
  const save = await screen.findByRole('button', { name: 'Save AI service settings' });
  await waitFor(() => expect((save as HTMLButtonElement).disabled).toBe(false));
  save.focus();
  fireEvent.click(save);
  await waitFor(() => expect(save.closest('fieldset')?.disabled).toBe(true));
  finish(INFER_DEFAULT);
  await waitFor(() => expect(save.closest('fieldset')?.disabled).toBe(false));
  expect(document.activeElement).toBe(save);
});

it('does not steal focus back when the user switches categories during a save', async () => {
  let finish!: (value: typeof INFER_DEFAULT) => void;
  apiMock.updateInferenceConfig.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  mount();
  const save = await screen.findByRole('button', { name: 'Save AI service settings' });
  await waitFor(() => expect((save as HTMLButtonElement).disabled).toBe(false));
  save.focus(); fireEvent.click(save);
  const destination = screen.getByRole('link', { name: 'Document processing' });
  destination.focus(); fireEvent.click(destination);
  finish(INFER_DEFAULT);
  await waitFor(() => expect(save.closest('fieldset')?.disabled).toBe(false));
  expect(document.activeElement).toBe(destination);
});

it('keeps the AI save label stable and blocks duplicate submission while busy', async () => {
  let reject!: (error: Error) => void;
  apiMock.updateInferenceConfig.mockClear().mockReturnValueOnce(new Promise((_, r) => { reject = r; }));
  mount();
  const save = await screen.findByRole('button', { name: 'Save AI service settings' }) as HTMLButtonElement;
  await waitFor(() => expect(save.disabled).toBe(false));
  fireEvent.click(save);
  await waitFor(() => expect(save.getAttribute('aria-busy')).toBe('true'));
  expect(save.textContent).toBe('Save AI Service Settings');
  fireEvent.click(save);
  expect(apiMock.updateInferenceConfig).toHaveBeenCalledTimes(1);
  reject(new Error('Synthetic connection failure'));
  await screen.findByText('Synthetic connection failure');
  expect(save.disabled).toBe(false);
});
