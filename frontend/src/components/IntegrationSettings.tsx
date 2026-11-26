import { ActionButton } from './ActionButton';
import { SectionIcon } from './SectionIcon';
/**
 * Application Settings component for configuring Slack, Teams, and Jira.
 * Toggle integrations, enter credentials, and test connections.
 */

import { useState, useEffect, useRef, useCallback, type CSSProperties } from 'react';
import { api, type DocumentProvider, type EmailConfigResponse, type LdapSettingsResponse, type SmtpSecurityMode, type SslVerifyMode } from '../lib/api';

const HINT_STYLE: CSSProperties = {
  position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
  overflow: 'hidden', clipPath: 'inset(50%)', whiteSpace: 'nowrap', border: 0,
};

const LDAP_DEFAULTS: LdapSettingsResponse = {
  enabled: false,
  server_uri: '',
  service_bind_dn: '',
  user_search_base_dn: '',
  user_search_filter: '(sAMAccountName={username})',
  start_tls: false,
  require_tls: true,
  ssl_verify: 'full',
  ssl_ca_bundle: null,
  timeout_seconds: 10,
  email_attr: 'mail',
  display_name_attr: 'displayName',
  department_attr: 'department',
  external_id_attr: 'objectGUID',
  auto_approve: false,
  default_role: 'user',
  login_disabled: false,
  local_register_enabled: true,
};

const EMAIL_DEFAULTS: Omit<EmailConfigResponse, 'password_configured'> = {
  enabled: false,
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_security: 'starttls',
  from_address: '',
};

const DOCUMENTS_DEFAULTS = {
  provider: 'docling' as DocumentProvider,
  azure_endpoint: '',
  azure_timeout_seconds: 600,
  azure_ssl_verify: 'full' as SslVerifyMode,
  azure_ssl_ca_bundle: '',
};

export function IntegrationSettings({ onBack, onDirtyChange }: { onBack?: () => void; onDirtyChange?: (dirty: boolean) => void } = {}) {
  const categories = ['ai', 'documents', 'notifications', 'directory'] as const;
  type Category = typeof categories[number];
  function categoryFromHash(): Category {
    const value = window.location.hash.replace('#settings-', '');
    return categories.includes(value as Category) ? value as Category : 'ai';
  }
  const [category, setCategory] = useState<Category>(categoryFromHash);
  useEffect(() => {
    const restore = () => { const value = window.location.hash.replace('#settings-', ''); setCategory(['ai', 'documents', 'notifications', 'directory'].includes(value) ? value as Category : 'ai'); };
    window.addEventListener('hashchange', restore);
    return () => window.removeEventListener('hashchange', restore);
  }, []);
  const settingsRoot = useRef<HTMLDivElement>(null);
  const actionFocus = useRef<{ section: string; target: HTMLElement } | null>(null);
  const rememberActionFocus = (section: string) => {
    if (document.activeElement instanceof HTMLElement && settingsRoot.current?.contains(document.activeElement)) {
      actionFocus.current = { section, target: document.activeElement };
    }
  };
  useEffect(() => { settingsRoot.current?.scrollIntoView?.({ block: 'start' }); }, [category]);
  const [configs, setConfigs] = useState<Record<string, boolean>>({
    slack: false,
    teams: false,
    jira: false,
  });
  const [loading, setLoading] = useState(true);
  const [statusUnavailable, setStatusUnavailable] = useState(false);
  const [loadedSections, setLoadedSections] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [savingIntegration, setSavingIntegration] = useState<string | null>(null);
  const [configLoaded, setConfigLoaded] = useState(false);
  // Inference configuration (DB values override the .env defaults)
  const [form, setForm] = useState({
    ai_endpoint: '',
    ai_model: '',
    temperature: 0.7,
    max_tokens: 1500,
    timeout: 60,
    api_key: '',
    ssl_verify: 'full' as SslVerifyMode,
    ssl_ca_bundle: '',
  });
  const [showKey, setShowKey] = useState(false);
  const [aiKeyConfigured, setAiKeyConfigured] = useState(false);
  const [savingInference, setSavingInference] = useState(false);
  const [inferenceSaved, setInferenceSaved] = useState(false);
  const [inferenceError, setInferenceError] = useState<string | null>(null);
  const [doclingForm, setDoclingForm] = useState({
    server_url: '',
    timeout_seconds: 600,
    ssl_verify: 'full' as SslVerifyMode,
    ssl_ca_bundle: '',
  });
  const [savingDocling, setSavingDocling] = useState(false);
  const [doclingSaved, setDoclingSaved] = useState(false);
  const [doclingError, setDoclingError] = useState<string | null>(null);
  const [documentsForm, setDocumentsForm] = useState(DOCUMENTS_DEFAULTS);
  const [azureKeyConfigured, setAzureKeyConfigured] = useState(false);
  const [savingDocuments, setSavingDocuments] = useState(false);
  const [documentsSaved, setDocumentsSaved] = useState(false);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [ldapForm, setLdapForm] = useState<LdapSettingsResponse>(LDAP_DEFAULTS);
  const [savingLdap, setSavingLdap] = useState(false);
  const [testingLdap, setTestingLdap] = useState(false);
  const [ldapSaved, setLdapSaved] = useState(false);
  const [ldapError, setLdapError] = useState<string | null>(null);
  const [ldapTestSuccess, setLdapTestSuccess] = useState<string | null>(null);
  const [emailForm, setEmailForm] = useState(EMAIL_DEFAULTS);
  const [emailPasswordConfigured, setEmailPasswordConfigured] = useState(false);
  const [savingEmail, setSavingEmail] = useState(false);
  const [testingEmail, setTestingEmail] = useState(false);
  const [emailSaved, setEmailSaved] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailTestSuccess, setEmailTestSuccess] = useState<string | null>(null);
  const [emailTestError, setEmailTestError] = useState<string | null>(null);

  type ServiceSection = 'inference' | 'docling' | 'documents' | 'ldap' | 'email';
  const baselines = useRef({ inference: form, docling: doclingForm, documents: documentsForm, ldap: ldapForm, email: emailForm });
  const [serviceLoading, setServiceLoading] = useState<Record<string, boolean>>({});
  const generations = useRef<Record<string, number>>({});
  const loadService = useCallback(async (section: ServiceSection) => {
    const generation = (generations.current[section] || 0) + 1;
    generations.current[section] = generation;
    setServiceLoading(v => ({ ...v, [section]: true }));
    setLoadedSections(v => ({ ...v, [section]: false }));
    try {
      switch (section) {
        case 'inference': {
          setInferenceError(null);
          if (typeof api.getInferenceConfig !== 'function') throw new Error('Settings are unavailable on this server.');
          const c = await api.getInferenceConfig();
          if (generations.current[section] !== generation) return;
          if (!c || typeof c !== 'object' || Array.isArray(c) || !('ai_endpoint' in c)) throw new Error('Settings response unavailable.');
          const next = {
          ai_endpoint: c.ai_endpoint || '',
          ai_model: c.ai_model || '',
          temperature: typeof c.temperature === 'number' ? c.temperature : 0.7,
          max_tokens: typeof c.max_tokens === 'number' ? c.max_tokens : 1500,
          timeout: typeof c.timeout === 'number' ? c.timeout : 60,
          api_key: '',
          ssl_verify: c.ssl_verify || 'full',
          ssl_ca_bundle: c.ssl_ca_bundle || '',
        };
          setAiKeyConfigured(Boolean(c.api_key));
          baselines.current.inference = next;
          setForm(next);
          break;
        }
        case 'docling': {
          setDoclingError(null);
          if (typeof api.getDoclingConfig !== 'function') throw new Error('Settings are unavailable on this server.');
          const c = await api.getDoclingConfig();
          if (generations.current[section] !== generation) return;
          if (!c || typeof c !== 'object' || Array.isArray(c) || !('server_url' in c)) throw new Error('Settings response unavailable.');
          const next = {
          server_url: c.server_url || '',
          timeout_seconds: typeof c.timeout_seconds === 'number' ? c.timeout_seconds : 600,
          ssl_verify: c.ssl_verify || 'full',
          ssl_ca_bundle: c.ssl_ca_bundle || '',
        };
          baselines.current.docling = next;
          setDoclingForm(next);
          break;
        }
        case 'documents': {
          setDocumentsError(null);
          if (typeof api.getDocumentProcessingConfig !== 'function') throw new Error('Settings are unavailable on this server.');
          const c = await api.getDocumentProcessingConfig();
          if (generations.current[section] !== generation) return;
          if (!c || typeof c !== 'object' || Array.isArray(c) || !('provider' in c)) throw new Error('Settings response unavailable.');
          const next = {
            provider: c.provider || 'docling',
            azure_endpoint: c.azure_endpoint || '',
            azure_timeout_seconds: typeof c.azure_timeout_seconds === 'number' ? c.azure_timeout_seconds : 600,
            azure_ssl_verify: c.azure_ssl_verify || 'full',
            azure_ssl_ca_bundle: c.azure_ssl_ca_bundle || '',
          };
          baselines.current.documents = next;
          setDocumentsForm(next);
          setAzureKeyConfigured(c.api_key_configured === true);
          break;
        }
        case 'ldap': {
          setLdapError(null);
          if (typeof api.getLdapSettings !== 'function') throw new Error('Settings are unavailable on this server.');
          const c = await api.getLdapSettings();
          if (generations.current[section] !== generation) return;
          if (!c || typeof c !== 'object' || Array.isArray(c) || !('enabled' in c)) throw new Error('Settings response unavailable.');
          const next = {
            ...LDAP_DEFAULTS,
            ...c,
            ssl_ca_bundle: c.ssl_ca_bundle || '',
          };
          baselines.current.ldap = next;
          setLdapForm(next);
          break;
        }
        case 'email': {
          setEmailError(null);
          if (typeof api.getEmailConfig !== 'function') throw new Error('Settings are unavailable on this server.');
          const c = await api.getEmailConfig();
          if (generations.current[section] !== generation) return;
          if (!c || typeof c !== 'object' || Array.isArray(c) || !('smtp_host' in c)) throw new Error('Settings response unavailable.');
          const next = {
            enabled: c.enabled === true,
            smtp_host: c.smtp_host || '',
            smtp_port: typeof c.smtp_port === 'number' ? c.smtp_port : 587,
            smtp_username: c.smtp_username || '',
            smtp_security: c.smtp_security || 'starttls',
            from_address: c.from_address || '',
          };
          baselines.current.email = next;
          setEmailForm(next);
          setEmailPasswordConfigured(c.password_configured === true);
          break;
        }
      }
      setLoadedSections(v => ({ ...v, [section]: true }));
    } catch (err) {
      if (generations.current[section] !== generation) return;
      const message = err instanceof Error ? err.message : 'Unable to load settings';
      const report = { inference: setInferenceError, docling: setDoclingError, documents: setDocumentsError, ldap: setLdapError, email: setEmailError };
      report[section](message);
    } finally {
      if (generations.current[section] === generation) setServiceLoading(v => ({ ...v, [section]: false }));
    }
  }, []);
  useEffect(() => {
    for (const section of ['inference', 'docling', 'documents', 'ldap', 'email'] as const) void loadService(section);
    const pending = generations.current;
    return () => { for (const section of Object.keys(pending)) pending[section]++; };
  }, [loadService]);
  const serviceDirty = {
    inference: loadedSections.inference && JSON.stringify(form) !== JSON.stringify(baselines.current.inference),
    docling: loadedSections.docling && JSON.stringify(doclingForm) !== JSON.stringify(baselines.current.docling),
    documents: loadedSections.documents && JSON.stringify(documentsForm) !== JSON.stringify(baselines.current.documents),
    ldap: loadedSections.ldap && JSON.stringify(ldapForm) !== JSON.stringify(baselines.current.ldap),
    email: loadedSections.email && JSON.stringify(emailForm) !== JSON.stringify(baselines.current.email),
  };

  const clearValidation = (section: string) => {
    settingsRoot.current?.querySelectorAll(`[data-settings-section="${section}"] [aria-invalid]`).forEach(control => control.removeAttribute('aria-invalid'));
  };
  const validateSection = (section: string, platform?: string): boolean => {
    clearValidation(section);
    const group = settingsRoot.current?.querySelector<HTMLElement>(`[data-settings-section="${section}"]`);
    const controls = group?.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea') || [];
    for (const control of controls) {
      if (!control.willValidate || (platform && control.dataset.settingsPlatform !== platform)) continue;
      control.removeAttribute('aria-invalid');
      if (!control.validity.valid) {
        for (let parent = control.parentElement; parent && parent !== group; parent = parent.parentElement) if (parent instanceof HTMLDetailsElement) parent.open = true;
        control.setAttribute('aria-invalid', 'true');
        control.scrollIntoView?.({ block: 'center', behavior: 'auto' });
        control.focus();
        control.reportValidity();
        const fieldName = control.labels?.[0]?.textContent?.trim().split('\n')[0] || 'this field';
        const message = `${fieldName}: ${control.dataset.validationMessage || control.validationMessage}`;
        const report = { inference: setInferenceError, docling: setDoclingError, documents: setDocumentsError, ldap: setLdapError, email: setEmailError, integrations: setError };
        report[section as keyof typeof report]?.(message);
        return false;
      }
    }
    return true;
  };

  const saveInferenceConfig = async () => {
    if (!loadedSections.inference || savingInference) return;
    if (!validateSection('inference')) return;
    rememberActionFocus('inference');
    setSavingInference(true);
    setInferenceSaved(false);
    setInferenceError(null);
    try {
      // ai_endpoint / ai_model are the real InferenceConfig field names;
      // Empty strings retain existing saved values; server defaults apply when no override exists.
      const payload: Parameters<typeof api.updateInferenceConfig>[0] = {
        ai_endpoint: form.ai_endpoint.trim(),
        ai_model: form.ai_model.trim(),
        temperature: form.temperature,
        max_tokens: form.max_tokens,
        timeout: form.timeout,
        ssl_verify: form.ssl_verify,
        ssl_ca_bundle: form.ssl_verify === 'ca' ? form.ssl_ca_bundle : '',
      };
      if (form.api_key.trim()) {
        payload.api_key = form.api_key.trim();
      }
      const saved = await api.updateInferenceConfig(payload);
      if (saved && typeof saved === 'object') setAiKeyConfigured('api_key' in saved ? Boolean(saved.api_key) : Boolean(payload.api_key) || aiKeyConfigured);
      setForm((f) => ({ ...f, api_key: '' }));
      baselines.current.inference = { ...form, ...payload, ...(saved && typeof saved === 'object' && 'ai_endpoint' in saved ? { ai_endpoint: saved.ai_endpoint || '', ai_model: saved.ai_model || '' } : {}), api_key: '', ssl_ca_bundle: payload.ssl_ca_bundle || '' };
      setForm({ ...baselines.current.inference });
      setInferenceSaved(true);
    } catch (err: unknown) {
      setInferenceError(err instanceof Error ? err.message : 'Failed to save inference config');
    } finally {
      setSavingInference(false);

    }
  };

  const saveDoclingConfig = async () => {
    if (!loadedSections.docling || savingDocling) return;
    if (!validateSection('docling')) return;
    rememberActionFocus('docling');
    setSavingDocling(true);
    setDoclingSaved(false);
    setDoclingError(null);
    try {
      const saved = await api.updateDoclingConfig({
        server_url: doclingForm.server_url.trim(),
        timeout_seconds: doclingForm.timeout_seconds,
        ssl_verify: doclingForm.ssl_verify,
        ssl_ca_bundle: doclingForm.ssl_verify === 'ca' ? doclingForm.ssl_ca_bundle : '',
      });
      baselines.current.docling = { ...doclingForm, server_url: doclingForm.server_url.trim() || (saved && typeof saved === 'object' ? saved.server_url || '' : ''), ssl_ca_bundle: doclingForm.ssl_verify === 'ca' ? doclingForm.ssl_ca_bundle : '' };
      setDoclingForm({ ...baselines.current.docling });
      setDoclingSaved(true);
    } catch (err: unknown) {
      setDoclingError(err instanceof Error ? err.message : 'Failed to save Docling config');
    } finally {
      setSavingDocling(false);
    }
  };

  const saveDocumentsConfig = async () => {
    if (!loadedSections.documents || savingDocuments) return;
    if (!validateSection('documents')) return;
    rememberActionFocus('documents');
    setSavingDocuments(true);
    setDocumentsSaved(false);
    setDocumentsError(null);
    try {
      const saved = await api.updateDocumentProcessingConfig({
        provider: documentsForm.provider,
        azure_endpoint: documentsForm.azure_endpoint.trim(),
        azure_timeout_seconds: documentsForm.azure_timeout_seconds,
        azure_ssl_verify: documentsForm.azure_ssl_verify,
        azure_ssl_ca_bundle: documentsForm.azure_ssl_verify === 'ca' ? documentsForm.azure_ssl_ca_bundle.trim() : '',
      });
      if (saved && typeof saved.api_key_configured === 'boolean') {
        setAzureKeyConfigured(saved.api_key_configured);
      }
      baselines.current.documents = { ...documentsForm, azure_endpoint: documentsForm.azure_endpoint.trim() || (saved && typeof saved === 'object' ? saved.azure_endpoint || '' : ''), azure_ssl_ca_bundle: documentsForm.azure_ssl_ca_bundle };
      setDocumentsForm({ ...baselines.current.documents });
      setDocumentsSaved(true);
    } catch (err: unknown) {
      setDocumentsError(err instanceof Error ? err.message : 'Failed to save document processing config');
    } finally {
      setSavingDocuments(false);
    }
  };

  const saveLdapSettings = async () => {
    if (!loadedSections.ldap || savingLdap || testingLdap) return;
    if (!validateSection('ldap')) return;
    rememberActionFocus('ldap');
    setSavingLdap(true);
    setLdapSaved(false);
    setLdapError(null);
    setLdapTestSuccess(null);
    try {
      const saved = await api.updateLdapSettings({
        enabled: ldapForm.enabled,
        server_uri: ldapForm.server_uri.trim(),
        service_bind_dn: ldapForm.service_bind_dn.trim(),
        user_search_base_dn: ldapForm.user_search_base_dn.trim(),
        user_search_filter: ldapForm.user_search_filter.trim(),
        start_tls: ldapForm.start_tls,
        require_tls: ldapForm.require_tls,
        ssl_verify: ldapForm.ssl_verify,
        ssl_ca_bundle: ldapForm.ssl_verify === 'ca' ? (ldapForm.ssl_ca_bundle || '') : '',
        timeout_seconds: ldapForm.timeout_seconds,
        email_attr: ldapForm.email_attr.trim(),
        display_name_attr: ldapForm.display_name_attr.trim(),
        department_attr: ldapForm.department_attr.trim(),
        external_id_attr: ldapForm.external_id_attr.trim(),
        auto_approve: ldapForm.auto_approve,
        default_role: ldapForm.default_role,
        login_disabled: ldapForm.login_disabled,
        local_register_enabled: ldapForm.local_register_enabled,
      });
      setLdapForm({ ...saved, ssl_ca_bundle: saved.ssl_ca_bundle || '' });
      baselines.current.ldap = { ...saved, ssl_ca_bundle: saved.ssl_ca_bundle || '' };
      setLdapSaved(true);
    } catch (err: unknown) {
      setLdapError(err instanceof Error ? err.message : 'Failed to save directory authentication settings');
    } finally {
      setSavingLdap(false);
    }
  };

  const testLdapConnection = async () => {
    if (!loadedSections.ldap || serviceDirty.ldap || savingLdap || testingLdap) return;
    rememberActionFocus('ldap');
    setTestingLdap(true);
    setLdapError(null);
    setLdapTestSuccess(null);
    try {
      const result = await api.testLdapConnection();
      if (result.ok) {
        setLdapTestSuccess(`✓ Connected in ${result.latency_ms} ms`);
      } else {
        setLdapError(`✗ ${result.error || 'Directory connection failed'}`);
      }
    } catch (err: unknown) {
      setLdapError(`✗ ${err instanceof Error ? err.message : 'Directory connection failed'}`);
    } finally {
      setTestingLdap(false);
    }
  };
  const saveEmailSettings = async () => {
    if (!loadedSections.email || savingEmail || testingEmail) return;
    if (!validateSection('email')) return;
    rememberActionFocus('email');
    setSavingEmail(true);
    setEmailSaved(false);
    setEmailError(null);
    setEmailTestSuccess(null);
    setEmailTestError(null);
    try {
      const saved = await api.updateEmailConfig({
        enabled: emailForm.enabled,
        smtp_host: emailForm.smtp_host.trim(),
        smtp_port: emailForm.smtp_port,
        smtp_username: emailForm.smtp_username.trim(),
        smtp_security: emailForm.smtp_security,
        from_address: emailForm.from_address.trim(),
      });
      const next = { enabled: saved.enabled, smtp_host: saved.smtp_host || '', smtp_port: saved.smtp_port, smtp_username: saved.smtp_username || '', smtp_security: saved.smtp_security, from_address: saved.from_address || '' };
      baselines.current.email = next;
      setEmailForm({ ...next });
      setEmailPasswordConfigured(saved.password_configured === true);
      setEmailSaved(true);
    } catch (err: unknown) {
      setEmailError(err instanceof Error ? err.message : 'Failed to save email settings');
    } finally {
      setSavingEmail(false);
    }
  };

  const testEmailConnection = async () => {
    if (!loadedSections.email || savingEmail || testingEmail) return;
    rememberActionFocus('email');
    setTestingEmail(true);
    setEmailError(null);
    setEmailTestSuccess(null);
    setEmailTestError(null);
    try {
      const result = await api.testEmailConnection();
      if (result.ok) {
        setEmailTestSuccess('✓ Test email sent to your own address');
      } else {
        setEmailTestError(`✗ ${result.error || 'Email send failed'}`);
      }
    } catch (err: unknown) {
      setEmailTestError(`✗ ${err instanceof Error ? err.message : 'Email send failed'}`);
    } finally {
      setTestingEmail(false);
    }
  };
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [forms, setForms] = useState({
    slack_webhook: '',
    teams_webhook: '',
    jira_url: '',
    jira_api_key: '',
    jira_project_key: '',
  });
  const [testing, setTesting] = useState<string | null>(null);
  const [connectionTests, setConnectionTests] = useState<Record<string, string>>({});
  useEffect(() => {
    const pending = actionFocus.current;
    if (!pending) return;
    const busy: Record<string, boolean> = { inference: savingInference, docling: savingDocling, documents: savingDocuments, ldap: savingLdap || testingLdap, email: savingEmail || testingEmail, integrations: saving || !!testing };
    if (busy[pending.section]) return;
    actionFocus.current = null;
    const { target } = pending;
    if (!target.isConnected || target.closest('[hidden]')) return;
    if (document.activeElement !== document.body && document.activeElement !== target) return;
    if (!target.matches(':disabled')) target.focus();
    else {
      const error = settingsRoot.current?.querySelector<HTMLElement>(`#settings-${pending.section}-error`);
      if (error) { error.tabIndex = -1; error.focus(); }
    }
  }, [savingInference, savingDocling, savingDocuments, savingLdap, testingLdap, savingEmail, testingEmail, saving, testing]);
  // What the backend currently stores per platform (integration_<platform>
  // categories) — prefills the forms and drives clear-on-empty deletes.
  const [stored, setStored] = useState<Record<string, Record<string, any>>>({});

  const [integrationLoading, setIntegrationLoading] = useState(true);
  const integrationGeneration = useRef({ value: 0 });
  const integrationBaseline = useRef(forms);
  const integrationDirty = configLoaded && JSON.stringify(forms) !== JSON.stringify(integrationBaseline.current);
  const loadIntegrations = useCallback(async () => {
    const generation = ++integrationGeneration.current.value;
    setIntegrationLoading(true);
    setConfigLoaded(false);
    setError(null);
    try {
      const c = await api.getIntegrationConfig();
      if (generation !== integrationGeneration.current.value) return;
      if (!c || typeof c !== 'object' || Array.isArray(c)) throw new Error('Integration settings unavailable');
      const next = {
        slack_webhook: c.slack?.webhook_url || '', teams_webhook: c.teams?.webhook_url || '',
        jira_url: c.jira?.url || '', jira_api_key: c.jira?.api_key || '', jira_project_key: c.jira?.project_key || '',
      };
      setStored(c);
      integrationBaseline.current = next;
      setForms(next);
      setConfigLoaded(true);
    } catch (err) {
      if (generation === integrationGeneration.current.value) setError(err instanceof Error ? err.message : 'Integration settings unavailable');
    } finally {
      if (generation === integrationGeneration.current.value) setIntegrationLoading(false);
    }
  }, []);
  useEffect(() => {
    void loadIntegrations();
    const pending = integrationGeneration.current;
    return () => { pending.value++; };
  }, [loadIntegrations]);
  useEffect(() => { void loadStatus(); }, []);
  const loadStatus = async () => {
    try { setLoading(true); setStatusUnavailable(false); setConfigs(await api.integrationStatus()); }
    catch { setStatusUnavailable(true); }
    finally { setLoading(false); }
  };
  const anyDirty = integrationDirty || Object.values(serviceDirty).some(Boolean);
  useEffect(() => { onDirtyChange?.(anyDirty); return () => onDirtyChange?.(false); }, [anyDirty, onDirtyChange]);
  useEffect(() => {
    if (!anyDirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [anyDirty]);

  const handleInputChange = (field: string, value: string) => {
    setForms(prev => ({ ...prev, [field]: value }));
    setSuccess(null);
    setError(null);
    settingsRoot.current?.querySelectorAll('[data-settings-platform]').forEach(control => control.removeAttribute('aria-invalid'));
  };

  const testConnection = async (platform: 'slack' | 'teams') => {
    if (!configLoaded || saving || testing || forms[`${platform}_webhook`].trim() !== (stored[platform]?.webhook_url || '')) return;
    setSuccess(null);
    // UX audit #14: Test Connection sends a REAL outbound Slack/Teams post.
    // Confirm first so a misclick doesn't post to a production channel.
    if (!window.confirm(`Send a test message to the configured ${platform === 'slack' ? 'Slack' : 'Microsoft Teams'} channel?`)) {
      return;
    }
    try {
      rememberActionFocus('integrations');
      setTesting(platform);
      setError(null);
      const message = `Connection test from S-A-I-L at ${new Date().toISOString()}`;
      await (platform === 'slack' ? api.sendSlack : api.sendTeams)(message, 'Connection Test');
      setConnectionTests(current => ({ ...current, [platform]: 'Last test passed' }));
      setSuccess(`${platform === 'slack' ? 'Slack' : 'Teams'} connection successful!`);
    } catch (err) {
      setConnectionTests(current => ({ ...current, [platform]: 'Last test failed' }));
      setError(`Failed to connect to ${platform === 'slack' ? 'Slack' : 'Teams'}: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setTesting(null);
    }
  };

  const handleSave = async (only?: string) => {
    if (!configLoaded || saving || testing) return;
    if (!validateSection('integrations', only)) return;
    try {
      rememberActionFocus('integrations');
      setSaving(true);
      setSavingIntegration(only || 'all');
      setError(null);
      setSuccess(null);

      // Persist via the admin-config endpoints (integration_<platform>
      // categories). Previously this button claimed success without
      // persisting anything. Clearing a stored field deactivates the entry.
      const platforms: Array<{ id: string; values: Record<string, string> }> = [
        { id: 'slack', values: { webhook_url: forms.slack_webhook.trim() } },
        { id: 'teams', values: { webhook_url: forms.teams_webhook.trim() } },
        {
          id: 'jira',
          values: {
            url: forms.jira_url.trim(),
            api_key: forms.jira_api_key.trim(),
            project_key: forms.jira_project_key.trim(),
          },
        },
      ];
      for (const platform of platforms.filter(p => !only || p.id === only)) {
        const toSave: Record<string, string> = {};
        for (const [key, value] of Object.entries(platform.values)) {
          if (value) {
            toSave[key] = value;
          } else if (stored[platform.id]?.[key]) {
            await api.deleteConfigEntry(`integration_${platform.id}`, key);
          }
        }
        if (Object.keys(toSave).length > 0) {
          await api.updateIntegrationConfig(platform.id, toSave);
        }
      }

      // Re-read the stored state so the form mirrors the backend.
      try {
        const c: any = await api.getIntegrationConfig();
        const next: Record<string, Record<string, any>> = {};
        if (c?.slack?.webhook_url) next.slack = { webhook_url: c.slack.webhook_url };
        if (c?.teams?.webhook_url) next.teams = { webhook_url: c.teams.webhook_url };
        if (c?.jira && (c.jira.url || c.jira.api_key || c.jira.project_key)) {
          next.jira = { url: c.jira.url || '', api_key: c.jira.api_key || '', project_key: c.jira.project_key || '' };
        }
        setStored(next);
        integrationBaseline.current = { slack_webhook: next.slack?.webhook_url || '', teams_webhook: next.teams?.webhook_url || '', jira_url: next.jira?.url || '', jira_api_key: next.jira?.api_key || '', jira_project_key: next.jira?.project_key || '' };
        setForms(current => {
          const next = { ...current };
          for (const key of Object.keys(next) as Array<keyof typeof next>) {
            if (!only || key.startsWith(`${only}_`)) next[key] = integrationBaseline.current[key];
          }
          return next;
        });
      } catch { throw new Error('Saved values could not be verified'); }

      setConnectionTests(current => only ? { ...current, [only]: 'Not tested since last save' } : {});
      setSuccess('Integration settings saved successfully');
      loadStatus();
    } catch (err) {
      setConfigLoaded(false);
      setError(`Save did not complete. Some changes may already be saved. Refresh to reload stored settings before retrying. ${err instanceof Error ? err.message : ''}`);
    } finally {
      setSaving(false);
      setSavingIntegration(null);
    }
  };

  return (
    <div ref={settingsRoot} className="application-settings" style={{
      background: 'var(--neutral-0)',
      borderRadius: 'var(--radius)',
      boxShadow: 'var(--shadow-card)',
      padding: 'clamp(12px, 3vw, 28px)',
      maxWidth: 1120, margin: '0 auto', minWidth: 0, width: '100%', boxSizing: 'border-box',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <h1 style={{ margin: 0, fontSize: '1.5rem' }}><SectionIcon name="🔗" /> Application Settings</h1>
        {onBack && (
          <ActionButton variant="quiet" style={{ marginTop: 12 }} role="button" aria-label="Back to Dashboard" onClick={() => { if (!anyDirty || window.confirm('Discard unsaved application settings changes?')) onBack?.(); }}>
            ← Back to Dashboard
          </ActionButton>
        )}
      </div>

      <p style={{ color: 'var(--neutral-600)', marginTop: 0 }}>Configure the services that power AI, document processing, notifications and sign-in.</p>
      <nav aria-label="Application settings sections" style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 24 }}>
        <a href="#settings-ai" aria-current={category === 'ai' ? 'location' : undefined} onClick={event => { event.preventDefault(); if (category !== 'ai') window.history.pushState(null, '', '#settings-ai'); setCategory('ai'); }}>AI service</a>
        <a href="#settings-documents" aria-current={category === 'documents' ? 'location' : undefined} onClick={event => { event.preventDefault(); if (category !== 'documents') window.history.pushState(null, '', '#settings-documents'); setCategory('documents'); }}>Document processing</a>
        <a href="#settings-notifications" aria-current={category === 'notifications' ? 'location' : undefined} onClick={event => { event.preventDefault(); if (category !== 'notifications') window.history.pushState(null, '', '#settings-notifications'); setCategory('notifications'); }}>Notifications &amp; ticketing</a>
        <a href="#settings-directory" aria-current={category === 'directory' ? 'location' : undefined} onClick={event => { event.preventDefault(); if (category !== 'directory') window.history.pushState(null, '', '#settings-directory'); setCategory('directory'); }}>Sign-in &amp; directory</a>
      </nav>
      <div className="application-settings-content">
        {/* Inference Configuration */}
        <section id="settings-ai" aria-label="AI service" hidden={category !== 'ai'}><div className="settings-card" style={{ background: 'var(--neutral-0)', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', padding: '20px' }}><div role="status">{savingInference ? 'Saving settings…' : serviceLoading.inference ? 'Loading settings…' : !loadedSections.inference ? 'Settings unavailable' : serviceDirty.inference ? 'Unsaved changes' : inferenceSaved ? 'Settings saved successfully' : 'Saved configuration loaded'}</div>
          {!loadedSections.inference && !serviceLoading.inference && <ActionButton variant="quiet" type="button" onClick={() => void loadService('inference')}>Retry inference settings</ActionButton>}
          <fieldset data-settings-section="inference" aria-label="AI service settings" aria-describedby={'settings-inference-help' + (inferenceError ? ' settings-inference-error' : '')} disabled={!loadedSections.inference || savingInference} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} onChangeCapture={event => { (event.target as HTMLElement).removeAttribute('aria-invalid'); setInferenceError(null); setInferenceSaved(false); }}>


          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--neutral-800)' }}><SectionIcon name="🧭" /> AI service</h2>
              <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: 'var(--neutral-600)' }}>
                Choose the endpoint and model used for AI features. Saved values take precedence over server defaults.
              </p>
            </div>
            {inferenceSaved && (
              <span style={{ fontSize: '0.85rem', color: 'var(--status-positive)', fontWeight: 600 }}>✓ Saved</span>
            )}
          </div>
          <p id="settings-inference-help" className="settings-help">Endpoint and model are optional: leaving them blank keeps the current server configuration. Saved overrides take precedence over server defaults. Enter an API key only to replace it; blank keeps the existing key.</p>
          {inferenceError && loadedSections.inference && <p className="settings-help">Review the highlighted field or the server message below. Any unsaved changes are retained.</p>}
          {inferenceError && (
            <div id="settings-inference-error" role="alert" style={{ padding: '8px 10px', marginBottom: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.8rem' }}>
              {inferenceError}
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: '12px' }}>
            <label htmlFor="settings-ai-ai-endpoint" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              API Endpoint
              <input aria-describedby="settings-ai-ai-endpoint-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-ai-ai-endpoint" type="text" value={form.ai_endpoint}
                onChange={(e) => setForm({ ...form, ai_endpoint: e.target.value })}
                placeholder="https://api.openai.com/v1"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ai-ai-endpoint-hint" style={HINT_STYLE}>Optional. Blank keeps the current endpoint.</span>
            <label htmlFor="settings-ai-ai-model" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Model
              <input aria-describedby="settings-ai-ai-model-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-ai-ai-model" type="text" value={form.ai_model}
                onChange={(e) => setForm({ ...form, ai_model: e.target.value })}
                placeholder="nemotron-lightning"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ai-ai-model-hint" style={HINT_STYLE}>Optional. Blank keeps the current model.</span>



            <label htmlFor="settings-inference-api-key" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              API key (optional replacement)
              <span>{!loadedSections.inference ? 'API key status is unavailable until settings load.' : aiKeyConfigured ? 'A key is configured on the server.' : 'No API key is configured on the server.'}</span>
              <div style={{ display: 'flex', gap: '6px' }}>
                <input aria-describedby="settings-inference-api-key-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-inference-api-key" aria-label="Inference API key" autoComplete="new-password" type={showKey ? 'text' : 'password'} value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder="••••••••"
                  style={{ flex: 1, padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
                <button type="button" role="button" aria-label={showKey ? "Hide AI service API key" : "Show AI service API key"} aria-pressed={showKey}
                  onClick={() => setShowKey(!showKey)}
                  style={{ padding: '6px 10px', background: 'var(--neutral-200)', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem' }}>
                  {showKey ? '🙈 Hide' : '👁 Show'}
                </button>
              </div>
            </label><span id="settings-inference-api-key-hint" style={HINT_STYLE}>Optional replacement. Blank keeps the stored key.</span>
            <label htmlFor="settings-inference-ssl-verification-mode" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              TLS verification mode
              <select aria-describedby="settings-inference-ssl-verification-mode-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-inference-ssl-verification-mode" aria-label="Inference SSL verification mode" value={form.ssl_verify}
                onChange={(e) => setForm({ ...form, ssl_verify: e.target.value as SslVerifyMode })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}>
                <option value="full">Verify TLS (default)</option>
                <option value="skip">Skip TLS verification (high-risk — internal/dev only)</option>
                <option value="ca">Verify against custom CA bundle</option>
              </select>
            </label><span id="settings-inference-ssl-verification-mode-hint" style={HINT_STYLE}>Verify TLS by default. Custom CA mode requires a certificate.</span>

          </div>
          <details className="settings-advanced" open={form.ssl_verify === 'ca' || undefined}><summary>Advanced AI settings</summary><div className="settings-field-grid"><label htmlFor="settings-ai-timeout" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Timeout (seconds)
              <input aria-describedby="settings-ai-timeout-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-ai-timeout" type="number" step="any" required aria-valuetext={Number.isFinite(form.timeout) ? undefined : 'No value entered'} value={Number.isFinite(form.timeout) ? form.timeout : ''}
                onChange={(e) => setForm({ ...form, timeout: e.target.value === '' ? NaN : Number(e.target.value) })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ai-timeout-hint" style={HINT_STYLE}>Request timeout in seconds.</span><label htmlFor="settings-ai-temperature" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Temperature
              <input aria-describedby="settings-ai-temperature-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-ai-temperature" type="number" required step="0.1" min="0" max="2" aria-valuetext={Number.isFinite(form.temperature) ? undefined : 'No value entered'} value={Number.isFinite(form.temperature) ? form.temperature : ''}
                onChange={(e) => setForm({ ...form, temperature: e.target.value === '' ? NaN : Number(e.target.value) })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ai-temperature-hint" style={HINT_STYLE}>Response variation, from zero to two.</span><label htmlFor="settings-ai-max-tokens" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Maximum response tokens
              <input aria-describedby="settings-ai-max-tokens-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-ai-max-tokens" type="number" required aria-valuetext={Number.isFinite(form.max_tokens) ? undefined : 'No value entered'} value={Number.isFinite(form.max_tokens) ? form.max_tokens : ''}
                onChange={(e) => setForm({ ...form, max_tokens: e.target.value === '' ? NaN : Number(e.target.value) })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ai-max-tokens-hint" style={HINT_STYLE}>Maximum generated response length, in tokens.</span><label htmlFor="settings-inference-custom-ca-bundle" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Custom CA bundle (PEM)
              <textarea aria-describedby="settings-inference-custom-ca-bundle-hint" aria-errormessage={inferenceError ? 'settings-inference-error' : undefined} id="settings-inference-custom-ca-bundle" aria-label="Inference custom CA bundle" data-validation-message="Enter PEM certificate contents when custom CA verification is selected." value={form.ssl_ca_bundle}
                onChange={(e) => setForm({ ...form, ssl_ca_bundle: e.target.value })}
                disabled={form.ssl_verify !== 'ca'}
                placeholder={'PEM certificate(s), one or more -----BEGIN CERTIFICATE----- blocks'}
                rows={5} required
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.8rem', fontFamily: 'monospace', resize: 'vertical', opacity: form.ssl_verify === 'ca' ? 1 : 0.55 }} />
              <span style={{ color: 'var(--neutral-600)' }}>Applies when TLS verification mode is <code>ca</code>.</span>
            </label><span id="settings-inference-custom-ca-bundle-hint" style={HINT_STYLE}>PEM certificate contents. Required with custom CA verification.</span></div></details>
<ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingInference} type="button" role="button" aria-label="Save AI service settings"
            onClick={saveInferenceConfig} disabled={savingInference || !loadedSections.inference}>
            Save AI Service Settings
          </ActionButton>
        <ActionButton variant="quiet" type="button" disabled={!serviceDirty.inference} onClick={() => { clearValidation('inference'); setForm({ ...baselines.current.inference }); setInferenceSaved(false); setInferenceError(null); }}>Reset AI changes</ActionButton></fieldset>
</div></section>

        {/* Document Processing provider */}
        <section id="settings-documents" aria-labelledby="settings-documents-title" hidden={category !== 'documents'}>
          <h2 id="settings-documents-title"><SectionIcon name="📄" /> Document processing</h2>
          <p>Choose how uploaded documents are converted. Only the selected provider is used; Markdown is normalized within S-A-I-L.</p>
<div className="settings-card" style={{ background: 'var(--neutral-0)', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', padding: '20px' }}><div role="status">{savingDocuments ? 'Saving settings…' : serviceLoading.documents ? 'Loading settings…' : !loadedSections.documents ? 'Settings unavailable' : serviceDirty.documents ? 'Unsaved changes' : documentsSaved ? 'Settings saved successfully' : 'Saved configuration loaded'}</div>
          {!loadedSections.documents && !serviceLoading.documents && <ActionButton variant="quiet" type="button" onClick={() => void loadService('documents')}>Retry documents settings</ActionButton>}
          <fieldset data-settings-section="documents" aria-label="Document provider settings" aria-describedby={'settings-documents-help' + (documentsError ? ' settings-documents-error' : '')} disabled={!loadedSections.documents || savingDocuments} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} onChangeCapture={event => { (event.target as HTMLElement).removeAttribute('aria-invalid'); setDocumentsError(null); setDocumentsSaved(false); }}>


          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-800)' }}><SectionIcon name="📄" /> Document provider</h3>
              <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: 'var(--neutral-600)' }}>
                Choose the provider that converts uploaded documents. Provider-specific settings are below.
              </p>
            </div>
            {documentsSaved && (
              <span style={{ fontSize: '0.85rem', color: 'var(--status-positive)', fontWeight: 600 }}>✓ Saved</span>
            )}
          </div>
          <p id="settings-documents-help" className="settings-help">Select the provider for future uploads; existing documents are not reprocessed. Azure requires an HTTPS endpoint at processing time. Its timeout must be between 1 and 3600 seconds. The Azure API key is managed on the server.</p>
          {documentsError && loadedSections.documents && <p className="settings-help">Review the highlighted field or the server message below. Any unsaved changes are retained.</p>}
          {documentsError && (
            <div id="settings-documents-error" role="alert" style={{ padding: '8px 10px', marginBottom: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.8rem' }}>
              {documentsError}
            </div>
          )}
          <label htmlFor="settings-document-provider" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', marginBottom: '12px' }}>
            Provider
            <select aria-describedby="settings-document-provider-hint" aria-errormessage={documentsError ? 'settings-documents-error' : undefined} id="settings-document-provider" aria-label="Document provider" value={documentsForm.provider}
              onChange={(e) => setDocumentsForm({ ...documentsForm, provider: e.target.value as DocumentProvider })}
              style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}>
              <option value="docling">Docling (local conversion server)</option>
              <option value="azure_document_intelligence">Azure Document Intelligence (Microsoft cloud)</option>
            </select>
          </label><span id="settings-document-provider-hint" style={HINT_STYLE}>Applies to future uploads. Existing documents are unchanged.</span>
          {documentsForm.provider === 'azure_document_intelligence' && (
            <p role="note" style={{ margin: '0 0 12px', padding: '10px', background: 'var(--status-warning-soft)', borderRadius: 'var(--radius)', fontSize: '0.85rem', color: 'var(--neutral-700)', lineHeight: 1.45 }}>
              When Azure Document Intelligence is selected, uploaded customer documents are sent to Microsoft Azure for processing.
            </p>
          )}
          <div hidden={documentsForm.provider !== 'azure_document_intelligence'} className="settings-provider-fields" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: '12px' }}>
            <label htmlFor="settings-azure-document-intelligence-endpoint" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Azure endpoint
              <input aria-describedby="settings-azure-document-intelligence-endpoint-hint" aria-errormessage={documentsError ? 'settings-documents-error' : undefined} id="settings-azure-document-intelligence-endpoint" aria-label="Azure Document Intelligence endpoint" data-validation-message="Enter an HTTPS endpoint, for example https://resource.cognitiveservices.azure.com." pattern="\s*https://.*" type="text" value={documentsForm.azure_endpoint}
                onChange={(e) => setDocumentsForm({ ...documentsForm, azure_endpoint: e.target.value })}
                disabled={documentsForm.provider !== 'azure_document_intelligence'}
                placeholder="https://<resource>.cognitiveservices.azure.com"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-azure-document-intelligence-endpoint-hint" style={HINT_STYLE}>Use the HTTPS endpoint for your Azure resource.</span>

            <label htmlFor="settings-azure-document-intelligence-ssl-verification-mode" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              TLS verification mode
              <select aria-describedby="settings-azure-document-intelligence-ssl-verification-mode-hint" aria-errormessage={documentsError ? 'settings-documents-error' : undefined} id="settings-azure-document-intelligence-ssl-verification-mode" aria-label="Azure Document Intelligence SSL verification mode" value={documentsForm.azure_ssl_verify}
                onChange={(e) => setDocumentsForm({ ...documentsForm, azure_ssl_verify: e.target.value as SslVerifyMode })}
                disabled={documentsForm.provider !== 'azure_document_intelligence'}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}>
                <option value="full">Verify TLS (default)</option>
                <option value="skip">Skip TLS verification (high-risk — internal/dev only)</option>
                <option value="ca">Verify against custom CA bundle</option>
              </select>
            </label><span id="settings-azure-document-intelligence-ssl-verification-mode-hint" style={HINT_STYLE}>Verify TLS by default. Custom CA mode requires a certificate.</span>

          </div>
          <p hidden={documentsForm.provider !== 'azure_document_intelligence'} style={{ margin: '12px 0 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
            {`API key: set in .env (SAIL_AZURE_DI_API_KEY) — ${azureKeyConfigured ? 'configured' : 'not configured'}`}
          </p>
<details className="settings-advanced"><summary>Supported document formats</summary><div style={{ overflowX: 'auto' }}>          <table aria-label="Provider capability matrix" style={{ width: '100%', marginTop: '12px', borderCollapse: 'collapse', fontSize: '0.85rem', color: 'var(--neutral-600)' }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--neutral-300)' }}>Provider</th>
                <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--neutral-300)' }}>Supported formats</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['Docling', 'PDF, CSV, TSV, TXT, DOC/DOCX, PPT/PPTX, XLS/XLSX, HTML, ODT/ODS/ODP, PNG, JPG, TIFF, BMP, WEBP'],
                ['Azure Document Intelligence', 'PDF, DOCX, XLSX, PPTX, HTML, PNG, JPG, TIFF, BMP, HEIF'],
                ['Both (no provider call)', '.md / .markdown (in-process normalization)'],
              ].map(([provider, formats]) => (
                <tr key={provider}>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--neutral-200)', whiteSpace: 'nowrap' }}>{provider}</td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--neutral-200)' }}>{formats}</td>
                </tr>
              ))}
            </tbody>
          </table></div></details>
          <details hidden={documentsForm.provider !== 'azure_document_intelligence'} className="settings-advanced" open={documentsForm.azure_ssl_verify === 'ca' || undefined}><summary>Advanced Azure settings</summary><div className="settings-field-grid"><label htmlFor="settings-azure-document-intelligence-timeout-seconds" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Timeout (seconds)
              <input aria-describedby="settings-azure-document-intelligence-timeout-seconds-hint" aria-errormessage={documentsError ? 'settings-documents-error' : undefined} id="settings-azure-document-intelligence-timeout-seconds" aria-label="Azure Document Intelligence timeout seconds" type="number" min="1" max="3600" step="any" required aria-valuetext={Number.isFinite(documentsForm.azure_timeout_seconds) ? undefined : 'No value entered'} value={Number.isFinite(documentsForm.azure_timeout_seconds) ? documentsForm.azure_timeout_seconds : ''}
                onChange={(e) => setDocumentsForm({ ...documentsForm, azure_timeout_seconds: e.target.value === '' ? NaN : Number(e.target.value) })}
                disabled={documentsForm.provider !== 'azure_document_intelligence'}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-azure-document-intelligence-timeout-seconds-hint" style={HINT_STYLE}>Between 1 and 3600 seconds.</span><label htmlFor="settings-azure-document-intelligence-custom-ca-bundle" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Custom CA bundle (PEM)
              <textarea aria-describedby="settings-azure-document-intelligence-custom-ca-bundle-hint" aria-errormessage={documentsError ? 'settings-documents-error' : undefined} id="settings-azure-document-intelligence-custom-ca-bundle" aria-label="Azure Document Intelligence custom CA bundle" data-validation-message="Enter PEM certificate contents when custom CA verification is selected." value={documentsForm.azure_ssl_ca_bundle}
                onChange={(e) => setDocumentsForm({ ...documentsForm, azure_ssl_ca_bundle: e.target.value })}
                disabled={documentsForm.provider !== 'azure_document_intelligence' || documentsForm.azure_ssl_verify !== 'ca'}
                placeholder={'PEM certificate(s), one or more -----BEGIN CERTIFICATE----- blocks'}
                rows={5} required
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.8rem', fontFamily: 'monospace', resize: 'vertical', opacity: documentsForm.azure_ssl_verify === 'ca' ? 1 : 0.55 }} />
              <span style={{ color: 'var(--neutral-600)' }}>Applies when TLS verification mode is <code>ca</code>.</span>
            </label><span id="settings-azure-document-intelligence-custom-ca-bundle-hint" style={HINT_STYLE}>PEM certificate contents. Required with custom CA verification.</span></div></details>
<ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingDocuments} type="button" role="button" aria-label="Save document processing settings"
            onClick={saveDocumentsConfig} disabled={savingDocuments || !loadedSections.documents}>
            Save Document Processing Settings
          </ActionButton>
        <ActionButton variant="quiet" type="button" disabled={!serviceDirty.documents} onClick={() => { clearValidation('documents'); setDocumentsForm({ ...baselines.current.documents }); setDocumentsSaved(false); setDocumentsError(null); }}>Reset document provider changes</ActionButton></fieldset>
</div>

        {/* Docling Configuration */}
        <div hidden={documentsForm.provider !== 'docling'} className="settings-card" style={{ background: 'var(--neutral-0)', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', padding: '20px' }}><div role="status">{savingDocling ? 'Saving settings…' : serviceLoading.docling ? 'Loading settings…' : !loadedSections.docling ? 'Settings unavailable' : serviceDirty.docling ? 'Unsaved changes' : doclingSaved ? 'Settings saved successfully' : 'Saved configuration loaded'}</div>
          {!loadedSections.docling && !serviceLoading.docling && <ActionButton variant="quiet" type="button" onClick={() => void loadService('docling')}>Retry docling settings</ActionButton>}
          <fieldset data-settings-section="docling" aria-label="Docling connection settings" aria-describedby={'settings-docling-help' + (doclingError ? ' settings-docling-error' : '')} disabled={!loadedSections.docling || savingDocling} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} onChangeCapture={event => { (event.target as HTMLElement).removeAttribute('aria-invalid'); setDoclingError(null); setDoclingSaved(false); }}>


          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-800)' }}><SectionIcon name="🔗" /> Docling connection</h3>
              <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: 'var(--neutral-600)' }}>
                Docling converts uploads when selected as the document provider. Azure uses its own connection settings.
              </p>
            </div>
            {doclingSaved && (
              <span style={{ fontSize: '0.85rem', color: 'var(--status-positive)', fontWeight: 600 }}>✓ Saved</span>
            )}
          </div>
          <p id="settings-docling-help" className="settings-help">The server URL is optional when already configured on the server. Timeout is in seconds. Use the default TLS verification unless your service requires a custom certificate.</p>
          {doclingError && loadedSections.docling && <p className="settings-help">Review the highlighted field or the server message below. Any unsaved changes are retained.</p>}
          {doclingError && (
            <div id="settings-docling-error" role="alert" style={{ padding: '8px 10px', marginBottom: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.8rem' }}>
              {doclingError}
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: '12px' }}>
            <label htmlFor="settings-docling-server-url" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Server URL
              <input aria-describedby="settings-docling-server-url-hint" aria-errormessage={doclingError ? 'settings-docling-error' : undefined} id="settings-docling-server-url" aria-label="Docling server URL" type="text" value={doclingForm.server_url}
                onChange={(e) => setDoclingForm({ ...doclingForm, server_url: e.target.value })}
                placeholder="http://docling:5001"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-docling-server-url-hint" style={HINT_STYLE}>Optional. Blank keeps the current server URL.</span>

            <label htmlFor="settings-docling-ssl-verification-mode" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              TLS verification mode
              <select aria-describedby="settings-docling-ssl-verification-mode-hint" aria-errormessage={doclingError ? 'settings-docling-error' : undefined} id="settings-docling-ssl-verification-mode" aria-label="Docling SSL verification mode" value={doclingForm.ssl_verify}
                onChange={(e) => setDoclingForm({ ...doclingForm, ssl_verify: e.target.value as SslVerifyMode })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}>
                <option value="full">Verify TLS (default)</option>
                <option value="skip">Skip TLS verification (high-risk — internal/dev only)</option>
                <option value="ca">Verify against custom CA bundle</option>
              </select>
            </label><span id="settings-docling-ssl-verification-mode-hint" style={HINT_STYLE}>Verify TLS by default. Custom CA mode requires a certificate.</span>

          </div>
          <p style={{ margin: '12px 0 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
            Docling API key is set via the <code>SAIL_DOCLING_API_KEY</code> environment variable (not editable here).
          </p>
          <details className="settings-advanced" open={doclingForm.ssl_verify === 'ca' || undefined}><summary>Advanced Docling settings</summary><div className="settings-field-grid"><label htmlFor="settings-docling-timeout-seconds" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Timeout (seconds)
              <input aria-describedby="settings-docling-timeout-seconds-hint" aria-errormessage={doclingError ? 'settings-docling-error' : undefined} id="settings-docling-timeout-seconds" aria-label="Docling timeout seconds" type="number" step="any" required aria-valuetext={Number.isFinite(doclingForm.timeout_seconds) ? undefined : 'No value entered'} value={Number.isFinite(doclingForm.timeout_seconds) ? doclingForm.timeout_seconds : ''}
                onChange={(e) => setDoclingForm({ ...doclingForm, timeout_seconds: e.target.value === '' ? NaN : Number(e.target.value) })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-docling-timeout-seconds-hint" style={HINT_STYLE}>Document conversion timeout in seconds.</span><label htmlFor="settings-docling-custom-ca-bundle" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Custom CA bundle (PEM)
              <textarea aria-describedby="settings-docling-custom-ca-bundle-hint" aria-errormessage={doclingError ? 'settings-docling-error' : undefined} id="settings-docling-custom-ca-bundle" aria-label="Docling custom CA bundle" data-validation-message="Enter PEM certificate contents when custom CA verification is selected." value={doclingForm.ssl_ca_bundle}
                onChange={(e) => setDoclingForm({ ...doclingForm, ssl_ca_bundle: e.target.value })}
                disabled={doclingForm.ssl_verify !== 'ca'}
                placeholder={'PEM certificate(s), one or more -----BEGIN CERTIFICATE----- blocks'}
                rows={5} required
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.8rem', fontFamily: 'monospace', resize: 'vertical', opacity: doclingForm.ssl_verify === 'ca' ? 1 : 0.55 }} />
              <span style={{ color: 'var(--neutral-600)' }}>Applies when TLS verification mode is <code>ca</code>.</span>
            </label><span id="settings-docling-custom-ca-bundle-hint" style={HINT_STYLE}>PEM certificate contents. Required with custom CA verification.</span></div></details>
<ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingDocling} type="button" role="button" aria-label="Save Docling settings"
            onClick={saveDoclingConfig} disabled={savingDocling || !loadedSections.docling}>
            Save Docling Settings
          </ActionButton>
        <ActionButton variant="quiet" type="button" disabled={!serviceDirty.docling} onClick={() => { clearValidation('docling'); setDoclingForm({ ...baselines.current.docling }); setDoclingSaved(false); setDoclingError(null); }}>Reset Docling changes</ActionButton></fieldset>
</div></section>

      </div>
      <section id="settings-notifications" hidden={category !== 'notifications'} aria-label="Notifications and ticketing" style={{ scrollMarginTop: 24 }}>
        <h2><SectionIcon name="🔔" /> Notifications &amp; ticketing</h2>
        <div id="settings-email-card" className="settings-card" style={{ background: 'var(--neutral-0)', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', padding: '20px', marginBottom: '1.5rem' }}><div role="status">{savingEmail ? 'Saving settings…' : serviceLoading.email ? 'Loading settings…' : !loadedSections.email ? 'Settings unavailable' : serviceDirty.email ? 'Unsaved changes' : emailSaved ? 'Settings saved successfully' : 'Saved configuration loaded'}</div>
          {!loadedSections.email && !serviceLoading.email && <ActionButton variant="quiet" type="button" onClick={() => void loadService('email')}>Retry email settings</ActionButton>}
          <h4 style={{ margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '8px' }}><SectionIcon name="📧" />Email notifications</h4>
          <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Send application notifications by email through your SMTP server.</p>
          <p id="settings-email-help" className="settings-help">The SMTP password is set in the environment (SAIL_EMAIL_SMTP_PASSWORD) and is never stored in the application. Saving requires a host and a From address; enabling sends email for new in-app notifications.</p>
          <div className="settings-integration-status">
            <span>Changes take effect after saving</span>
            <strong>Email configuration</strong>
            <span>{emailForm.enabled && emailForm.smtp_host && emailForm.from_address ? 'Configured' : 'Not configured'} · {emailTestSuccess || emailTestError || 'Not tested in this session'}</span>
          </div>
          {emailError && loadedSections.email && <p className="settings-help">Review the highlighted field or the server message below. Any unsaved changes are retained.</p>}
          {emailError && (
            <div id="settings-email-error" role="alert" style={{ padding: '8px 10px', marginBottom: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.8rem' }}>
              {emailError}
            </div>
          )}
          <fieldset data-settings-section="email" aria-label="Email notification settings" aria-describedby={'settings-email-help' + (emailError ? ' settings-email-error' : '')} disabled={!loadedSections.email || savingEmail || testingEmail} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} onChangeCapture={event => { (event.target as HTMLElement).removeAttribute('aria-invalid'); setEmailError(null); setEmailSaved(false); setEmailTestSuccess(null); setEmailTestError(null); }}>
          <label htmlFor="settings-email-enabled" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px', fontSize: '0.85rem' }}>
            <input aria-describedby="settings-email-enabled-hint" aria-errormessage={emailError ? 'settings-email-error' : undefined} id="settings-email-enabled" type="checkbox" checked={emailForm.enabled} onChange={(e) => setEmailForm({ ...emailForm, enabled: e.target.checked })} />
            Enable email notifications
          </label><span id="settings-email-enabled-hint" style={HINT_STYLE}>While disabled, notifications remain in-app only.</span>
          <div className="settings-field-grid">
            <label htmlFor="settings-email-smtp-host" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              SMTP host
              <input aria-describedby="settings-email-smtp-host-hint" aria-errormessage={emailError ? 'settings-email-error' : undefined} id="settings-email-smtp-host" type="text" value={emailForm.smtp_host} onChange={(e) => setEmailForm({ ...emailForm, smtp_host: e.target.value })} placeholder="smtp.example.com" style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-email-smtp-host-hint" style={HINT_STYLE}>Your mail server (e.g. smtp.example.com).</span>
            <label htmlFor="settings-email-smtp-port" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              SMTP port
              <input aria-describedby="settings-email-smtp-port-hint" aria-errormessage={emailError ? 'settings-email-error' : undefined} id="settings-email-smtp-port" type="number" step="1" required min="1" max="65535" aria-valuetext={Number.isFinite(emailForm.smtp_port) ? undefined : 'No value entered'} value={Number.isFinite(emailForm.smtp_port) ? emailForm.smtp_port : ''} onChange={(e) => setEmailForm({ ...emailForm, smtp_port: e.target.value === '' ? NaN : Number(e.target.value) })} style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-email-smtp-port-hint" style={HINT_STYLE}>587 for STARTTLS, 465 for implicit TLS.</span>
            <label htmlFor="settings-email-smtp-username" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              SMTP username
              <input aria-describedby="settings-email-smtp-username-hint" aria-errormessage={emailError ? 'settings-email-error' : undefined} id="settings-email-smtp-username" type="text" autoComplete="off" value={emailForm.smtp_username} onChange={(e) => setEmailForm({ ...emailForm, smtp_username: e.target.value })} style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-email-smtp-username-hint" style={HINT_STYLE}>Leave blank when the server requires no authentication.</span>
            <label htmlFor="settings-email-smtp-security" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Transport security
              <select aria-errormessage={emailError ? 'settings-email-error' : undefined} id="settings-email-smtp-security" value={emailForm.smtp_security} onChange={(e) => setEmailForm({ ...emailForm, smtp_security: e.target.value as SmtpSecurityMode })} style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }}>
                <option value="starttls">STARTTLS (port 587)</option>
                <option value="ssl">Implicit TLS / SSL (port 465)</option>
                <option value="none">No TLS (not recommended)</option>
              </select>
            </label>
            <label htmlFor="settings-email-from-address" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              From address
              <input aria-describedby="settings-email-from-address-hint" aria-errormessage={emailError ? 'settings-email-error' : undefined} id="settings-email-from-address" type="email" value={emailForm.from_address} onChange={(e) => setEmailForm({ ...emailForm, from_address: e.target.value })} placeholder="sail@example.com" style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-email-from-address-hint" style={HINT_STYLE}>The sender address of outgoing notification mail.</span>
          </div>
          <p id="settings-email-password-line" className="settings-help">SMTP password: set in .env (SAIL_EMAIL_SMTP_PASSWORD) — {emailPasswordConfigured ? 'configured' : 'not configured'}</p>
          <ActionButton variant="quiet" type="button" disabled={!serviceDirty.email} onClick={() => { clearValidation('email'); setEmailForm({ ...baselines.current.email }); setEmailSaved(false); setEmailError(null); }}>Reset email changes</ActionButton>
          <ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingEmail} type="button" onClick={saveEmailSettings} disabled={!loadedSections.email || savingEmail || testingEmail}>Save Email Settings</ActionButton>
          <span style={{ fontSize: '0.8rem' }}>Tests saved settings and sends a test email to your own address. Save or reset changes first.</span>
          <ActionButton variant="secondary" style={{ marginTop: 12 }} busy={testingEmail} type="button" aria-label="Test email connection" onClick={testEmailConnection} disabled={!loadedSections.email || savingEmail || !!testingEmail || serviceDirty.email}>Test Connection</ActionButton>
          {emailTestSuccess && <span role="status" style={{ marginLeft: 8, fontSize: '0.8rem', color: 'var(--status-positive)' }}>{emailTestSuccess}</span>}
          {emailTestError && <span role="status" style={{ marginLeft: 8, fontSize: '0.8rem', color: 'var(--status-negative)' }}>{emailTestError}</span>}
          </fieldset>
        </div>
        <div role="status">{integrationLoading ? 'Loading integration settings…' : !configLoaded ? 'Integration settings unavailable' : integrationDirty ? 'Unsaved integration changes' : 'Saved integration configuration loaded'}{loading && ' · Checking configuration status…'}</div>
        {!configLoaded && !integrationLoading && <ActionButton variant="quiet" type="button" onClick={() => void loadIntegrations()}>Retry integration settings</ActionButton>}
      {error && (
        <div id="settings-integrations-error" role="alert" style={{
          padding: '10px',
          background: 'var(--status-negative-soft)',
          borderRadius: 'var(--radius)',
          color: 'var(--status-negative)',
          marginBottom: '1rem',
          fontSize: '0.9rem',
        }}>
          {error}
        </div>
      )}

      {success && (
        <div role="status" style={{
          padding: '10px',
          background: 'var(--status-positive-soft)',
          borderRadius: 'var(--radius)',
          color: 'var(--status-positive)',
          marginBottom: '1rem',
          fontSize: '0.9rem',
        }}>
          {success}
        </div>
      )}

        <fieldset data-settings-section="integrations" aria-label="Notification and ticket integrations" disabled={!configLoaded || saving || !!testing} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <ActionButton variant="quiet" type="button" disabled={!integrationDirty} onClick={() => { setForms({ ...integrationBaseline.current }); setSuccess(null); setError(null); }}>Reset integration changes</ActionButton>

      {/* Slack Integration */}
      <div style={{ marginBottom: '2rem', paddingBottom: '1.5rem', borderBottom: '1px solid var(--divider)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SectionIcon name="💬" />
          Slack Integration
        </h4>
        <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
          Connect Slack to receive notifications about use case updates and scoring results.
        </p>

        <p id="settings-slack-help" className="settings-help">Paste the incoming Slack webhook URL. Leave blank to keep this integration unconfigured; clearing a saved URL removes it when you save.</p>
        <div className="settings-integration-status">
          <span>Changes take effect after saving</span>
          <strong>Slack configuration</strong>
          <span>{loading ? 'Checking configuration…' : statusUnavailable ? 'Configuration status unavailable' : configs.slack ? 'Configured' : 'Not configured'} · {connectionTests.slack || 'Not tested in this session'}</span>
        </div>

        <div style={{ marginBottom: '0.75rem' }}>
          <label htmlFor="settings-slack-webhook-url" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', fontWeight: 500 }}>
            Webhook URL
          </label><span id="settings-slack-webhook-url-hint" style={HINT_STYLE}>Incoming Slack webhook. Clearing a saved URL removes it when saved.</span>
          <input id="settings-slack-webhook-url" data-settings-platform="slack" aria-describedby="settings-slack-webhook-url-hint" aria-errormessage={error ? 'settings-integrations-error' : undefined} aria-label="Slack webhook URL"
            type="url"
            placeholder="https://hooks.slack.com/services/..."
            value={forms.slack_webhook}
            onChange={(e) => handleInputChange('slack_webhook', e.target.value)}
            disabled={!configLoaded || saving}
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid var(--divider)',
              borderRadius: 'var(--radius-sm)',
              boxSizing: 'border-box',
            }}
          />
        </div>

        <ActionButton variant="quiet" type="button" disabled={!configLoaded || saving || !!testing || !Object.keys(forms).some(key => key.startsWith('slack_') && forms[key as keyof typeof forms] !== integrationBaseline.current[key as keyof typeof forms])} onClick={() => { setForms(current => { const next = { ...current }; for (const key of Object.keys(next) as Array<keyof typeof next>) if (key.startsWith('slack_')) next[key] = integrationBaseline.current[key]; return next; }); setSuccess(null); }}>Reset Slack changes</ActionButton>
        <ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingIntegration === 'slack'} type="button" aria-label="Save Slack settings" disabled={saving || !configLoaded || !!testing} onClick={() => handleSave('slack')}>Save Slack Settings</ActionButton>
        <p>Connection tests use saved settings and send a real message. Save changes before testing.</p>
        <ActionButton variant="secondary" style={{ marginTop: 12 }} busy={testing === 'slack'} role="button" aria-label="Test Slack connection"
          onClick={() => testConnection('slack')}
          disabled={!!testing || saving || !configLoaded || !forms.slack_webhook || forms.slack_webhook.trim() !== (stored.slack?.webhook_url || '')}
        >
          Test Connection
        </ActionButton>
      </div>

      {/* Microsoft Teams Integration */}
      <div style={{ marginBottom: '2rem', paddingBottom: '1.5rem', borderBottom: '1px solid var(--divider)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SectionIcon name="👥" />
          Microsoft Teams Integration
        </h4>
        <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
          Connect Teams to receive notifications about use case updates and scoring results.
        </p>

        <p id="settings-teams-help" className="settings-help">Paste the incoming Microsoft Teams webhook URL. Clearing a saved URL removes it when you save.</p>
        <div className="settings-integration-status">
          <span>Changes take effect after saving</span>
          <strong>Teams configuration</strong>
          <span>{loading ? 'Checking configuration…' : statusUnavailable ? 'Configuration status unavailable' : configs.teams ? 'Configured' : 'Not configured'} · {connectionTests.teams || 'Not tested in this session'}</span>
        </div>

        <div style={{ marginBottom: '0.75rem' }}>
          <label htmlFor="settings-microsoft-teams-webhook-url" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', fontWeight: 500 }}>
            Webhook URL
          </label><span id="settings-microsoft-teams-webhook-url-hint" style={HINT_STYLE}>Incoming Teams webhook. Clearing a saved URL removes it when saved.</span>
          <input id="settings-microsoft-teams-webhook-url" data-settings-platform="teams" aria-describedby="settings-microsoft-teams-webhook-url-hint" aria-errormessage={error ? 'settings-integrations-error' : undefined} aria-label="Microsoft Teams webhook URL"
            type="url"
            placeholder="https://outlook.office.com/webhook/..."
            value={forms.teams_webhook}
            onChange={(e) => handleInputChange('teams_webhook', e.target.value)}
            disabled={!configLoaded || saving}
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid var(--divider)',
              borderRadius: 'var(--radius-sm)',
              boxSizing: 'border-box',
            }}
          />
        </div>

        <ActionButton variant="quiet" type="button" disabled={!configLoaded || saving || !!testing || !Object.keys(forms).some(key => key.startsWith('teams_') && forms[key as keyof typeof forms] !== integrationBaseline.current[key as keyof typeof forms])} onClick={() => { setForms(current => { const next = { ...current }; for (const key of Object.keys(next) as Array<keyof typeof next>) if (key.startsWith('teams_')) next[key] = integrationBaseline.current[key]; return next; }); setSuccess(null); }}>Reset Teams changes</ActionButton>
        <ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingIntegration === 'teams'} type="button" aria-label="Save Teams settings" disabled={saving || !configLoaded || !!testing} onClick={() => handleSave('teams')}>Save Teams Settings</ActionButton>
        <p>Connection tests use saved settings and send a real message. Save changes before testing.</p>
        <ActionButton variant="secondary" style={{ marginTop: 12 }} busy={testing === 'teams'} role="button" aria-label="Test Microsoft Teams connection"
          onClick={() => testConnection('teams')}
          disabled={!!testing || saving || !configLoaded || !forms.teams_webhook || forms.teams_webhook.trim() !== (stored.teams?.webhook_url || '')}
        >
          Test Connection
        </ActionButton>
      </div>

      {/* Jira Integration */}
      <div style={{ marginBottom: '1.5rem' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SectionIcon name="🎫" />
          Jira Integration
        </h4>
        <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
          Create Jira tickets from use cases for tracking and project management.
        </p>

        <p id="settings-jira-help" className="settings-help">Enter the Jira URL, project key and API token to configure ticket creation. Clearing a saved value removes that value when you save. The token is hidden; no token is included in status messages.</p>
        <div className="settings-integration-status">
          <span>Changes take effect after saving</span>
          <strong>Jira configuration</strong>
          <span>{loading ? 'Checking configuration…' : statusUnavailable ? 'Configuration status unavailable' : configs.jira ? 'Configured' : 'Not configured'}</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: '0.75rem', marginBottom: '0.75rem' }}>
          <div>
            <label htmlFor="settings-jira-url" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', fontWeight: 500 }}>
              Jira URL
            </label><span id="settings-jira-url-hint" style={HINT_STYLE}>Base URL of your Jira site.</span>
            <input id="settings-jira-url" data-settings-platform="jira" aria-describedby="settings-jira-url-hint" aria-errormessage={error ? 'settings-integrations-error' : undefined} aria-label="Jira URL"
              type="url"
              placeholder="https://yourcompany.atlassian.net"
              value={forms.jira_url}
              onChange={(e) => handleInputChange('jira_url', e.target.value)}
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--divider)',
                borderRadius: 'var(--radius-sm)',
                boxSizing: 'border-box',
              }}
            />
          </div>
          <div>
            <label htmlFor="settings-jira-project-key" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', fontWeight: 500 }}>
              Project Key
            </label><span id="settings-jira-project-key-hint" style={HINT_STYLE}>Project key for new tickets.</span>
            <input id="settings-jira-project-key" data-settings-platform="jira" aria-describedby="settings-jira-project-key-hint" aria-errormessage={error ? 'settings-integrations-error' : undefined} aria-label="Jira project key"
              type="text"
              placeholder="AI"
              value={forms.jira_project_key}
              onChange={(e) => handleInputChange('jira_project_key', e.target.value)}
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--divider)',
                borderRadius: 'var(--radius-sm)',
                boxSizing: 'border-box',
              }}
            />
          </div>
        </div>

        <div style={{ marginBottom: '0.75rem' }}>
          <label htmlFor="settings-jira-api-token" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', fontWeight: 500 }}>
            API Key / Token
          </label><span id="settings-jira-api-token-hint" style={HINT_STYLE}>Hidden token. Clearing a saved token removes it when saved.</span>
          <input id="settings-jira-api-token" data-settings-platform="jira" aria-describedby="settings-jira-api-token-hint" aria-errormessage={error ? 'settings-integrations-error' : undefined} aria-label="Jira API token" autoComplete="new-password"
            type="password"
            placeholder="Your Jira API key"
            value={forms.jira_api_key}
            onChange={(e) => handleInputChange('jira_api_key', e.target.value)}
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid var(--divider)',
              borderRadius: 'var(--radius-sm)',
              boxSizing: 'border-box',
            }}
          />
        </div>

        <ActionButton variant="quiet" type="button" disabled={!configLoaded || saving || !!testing || !Object.keys(forms).some(key => key.startsWith('jira_') && forms[key as keyof typeof forms] !== integrationBaseline.current[key as keyof typeof forms])} onClick={() => { setForms(current => { const next = { ...current }; for (const key of Object.keys(next) as Array<keyof typeof next>) if (key.startsWith('jira_')) next[key] = integrationBaseline.current[key]; return next; }); setSuccess(null); }}>Reset Jira changes</ActionButton>
        <ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingIntegration === 'jira'} role="button" aria-label="Save Jira settings"
          onClick={() => handleSave('jira')}
          disabled={saving || !configLoaded || !!testing}
        >
          Save Jira Settings
        </ActionButton>
      </div>

      {/* Integration save action */}
      <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--divider)' }}>
        <ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingIntegration === 'all'} role="button" aria-label="Save all integration settings"
          onClick={() => handleSave()}
          disabled={saving || !configLoaded || !!testing}
        >
          Save All Integration Settings
        </ActionButton>
      </div>      </fieldset></section>
      <div style={{ minWidth: 0 }}>
        {/* Directory Authentication Configuration */}
        <section id="settings-directory" aria-label="Sign-in & directory" hidden={category !== 'directory'}><div className="settings-card" style={{ background: 'var(--neutral-0)', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', padding: '20px' }}><div role="status">{savingLdap ? 'Saving settings…' : serviceLoading.ldap ? 'Loading settings…' : !loadedSections.ldap ? 'Settings unavailable' : serviceDirty.ldap ? 'Unsaved changes' : ldapSaved ? 'Settings saved successfully' : 'Saved configuration loaded'}</div>
          {!loadedSections.ldap && !serviceLoading.ldap && <ActionButton variant="quiet" type="button" onClick={() => void loadService('ldap')}>Retry ldap settings</ActionButton>}
          <fieldset data-settings-section="ldap" aria-label="Directory sign-in settings" aria-describedby={'settings-ldap-help' + (ldapError ? ' settings-ldap-error' : '')} disabled={!loadedSections.ldap || savingLdap || testingLdap} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} onChangeCapture={event => { (event.target as HTMLElement).removeAttribute('aria-invalid'); setLdapError(null); setLdapSaved(false); setLdapTestSuccess(null); }}>


          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--neutral-800)' }}><SectionIcon name="🛡️" /> Sign-in & directory (LDAP/AD)</h2>
            {ldapSaved && (
              <span style={{ fontSize: '0.85rem', color: 'var(--status-positive)', fontWeight: 600 }}>✓ Saved</span>
            )}
          </div>
          <p style={{ margin: '0 0 14px', padding: '10px', background: 'var(--neutral-50)', borderRadius: 'var(--radius)', fontSize: '0.85rem', color: 'var(--neutral-500)', lineHeight: 1.45 }}>
            The service-account bind password is configured via the <code>SAIL_AUTH_LDAP_SERVICE_BIND_PASSWORD</code> environment variable (k8s Secret in production) — it is never stored in the app database.
          </p>
          <p id="settings-ldap-help" className="settings-help">Server URI, service bind DN and search base DN are required when directory sign-in is enabled. The bind password is managed on the server. LDAP changes do not change local administrator accounts.</p>
          {ldapError && loadedSections.ldap && <p className="settings-help">Review the highlighted field or the server message below. Any unsaved changes are retained.</p>}
          {ldapError && (
            <div id="settings-ldap-error" role="alert" style={{ padding: '8px 10px', marginBottom: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.8rem' }}>
              {ldapError}
            </div>
          )}
          {ldapTestSuccess && (
            <div role="status" style={{ padding: '8px 10px', marginBottom: '12px', background: 'var(--status-positive-soft)', borderRadius: 'var(--radius)', color: 'var(--status-positive)', fontSize: '0.8rem' }}>
              {ldapTestSuccess}
            </div>
          )}

          <label htmlFor="settings-enable-directory-authentication-ldap-ad" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px', fontSize: '0.85rem' }}>
            <input aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-enable-directory-authentication-ldap-ad" aria-label="Enable directory authentication (LDAP/AD)" type="checkbox"
              checked={ldapForm.enabled}
              onChange={(e) => setLdapForm({ ...ldapForm, enabled: e.target.checked })}
              style={{ width: '18px', height: '18px' }} />
            <strong>Enable directory authentication (LDAP/AD)</strong>
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: '12px' }}>
            <label htmlFor="settings-ldap-server-uri" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Server URI
              <input aria-describedby="settings-ldap-server-uri-hint" aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-server-uri" aria-label="LDAP server URI" required={ldapForm.enabled} type="text" value={ldapForm.server_uri}
                onChange={(e) => setLdapForm({ ...ldapForm, server_uri: e.target.value })}
                placeholder="ldaps://dc01.corp:636 — or ldap://dc01.corp:389 with StartTLS"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ldap-server-uri-hint" style={HINT_STYLE}>Required when directory sign-in is enabled. Use LDAPS or LDAP with StartTLS.</span>
            <label htmlFor="settings-ldap-service-bind-dn" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Service bind DN
              <input aria-describedby="settings-ldap-service-bind-dn-hint" aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-service-bind-dn" aria-label="LDAP service bind DN" required={ldapForm.enabled} type="text" value={ldapForm.service_bind_dn}
                onChange={(e) => setLdapForm({ ...ldapForm, service_bind_dn: e.target.value })}
                placeholder="CN=sil-svc,OU=ServiceAccounts,DC=corp,DC=local"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ldap-service-bind-dn-hint" style={HINT_STYLE}>Required when directory sign-in is enabled.</span>
            <label htmlFor="settings-ldap-search-base-dn" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Search base DN
              <input aria-describedby="settings-ldap-search-base-dn-hint" aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-search-base-dn" aria-label="LDAP search base DN" required={ldapForm.enabled} type="text" value={ldapForm.user_search_base_dn}
                onChange={(e) => setLdapForm({ ...ldapForm, user_search_base_dn: e.target.value })}
                placeholder="OU=Users,DC=corp,DC=local"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ldap-search-base-dn-hint" style={HINT_STYLE}>Required when directory sign-in is enabled.</span>


            <div style={{ gridColumn: '1 / -1', display: 'grid', gap: '8px', padding: '10px', background: 'var(--neutral-50)', borderRadius: 'var(--radius)' }}>
              {[
                ['start_tls', 'LDAP StartTLS', 'StartTLS (ldap://:389 upgrade)'],
                ['require_tls', 'LDAP require TLS', 'Require TLS (refuse plaintext)'],
                ['auto_approve', 'LDAP auto approve', 'Auto-approve directory users on first login'],
                ['login_disabled', 'LDAP login disabled', 'Directory login disabled (kill-switch; local accounts unaffected)'],
              ].map(([field, ariaLabel, label]) => (
                <label htmlFor={`settings-ldap-${field}`} key={field} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: 'var(--neutral-700)' }}>
                  <input aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id={`settings-ldap-${field}`} aria-label={ariaLabel} type="checkbox"
                    checked={ldapForm[field as keyof LdapSettingsResponse] as boolean}
                    onChange={(e) => setLdapForm({ ...ldapForm, [field]: e.target.checked })} />
                  {label}
                </label>
              ))}
            </div>

            <div style={{ gridColumn: '1 / -1', padding: '10px', border: '1px solid var(--neutral-200)', borderRadius: 'var(--radius)' }}>
              <p style={{ margin: '0 0 8px', fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-600)' }}>Local authentication</p>
              <label htmlFor="settings-ldap-local-registration-enabled" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: 'var(--neutral-700)' }}>
                <input aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-local-registration-enabled" aria-label="LDAP local registration enabled" type="checkbox"
                  checked={ldapForm.local_register_enabled}
                  onChange={(e) => setLdapForm({ ...ldapForm, local_register_enabled: e.target.checked })} />
                Allow local self-registration (hide the Register form when off)
              </label>
            </div>

            <label htmlFor="settings-ldap-ssl-verification-mode" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              TLS verification mode
              <select aria-describedby="settings-ldap-ssl-verification-mode-hint" aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-ssl-verification-mode" aria-label="LDAP SSL verification mode" value={ldapForm.ssl_verify}
                onChange={(e) => setLdapForm({ ...ldapForm, ssl_verify: e.target.value as SslVerifyMode })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}>
                <option value="full">Verify TLS (default)</option>
                <option value="skip">Skip TLS verification (high-risk — internal/dev only)</option>
                <option value="ca">Verify against custom CA bundle</option>
              </select>
            </label><span id="settings-ldap-ssl-verification-mode-hint" style={HINT_STYLE}>Verify TLS by default. Custom CA mode requires a certificate.</span>

            <label htmlFor="settings-ldap-default-role" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Default directory role
              <select aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-default-role" aria-label="LDAP default role" value={ldapForm.default_role}
                onChange={(e) => setLdapForm({ ...ldapForm, default_role: e.target.value })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}>
                <option value="user">User</option>
                <option value="auditor">Auditor</option>
                <option value="ps_admin">PS Admin</option>
              </select>
              <span style={{ color: 'var(--neutral-600)', lineHeight: 1.4 }}>admin is granted locally by an admin, never from the directory</span>
            </label>


            <details style={{ gridColumn: '1 / -1', padding: '10px', border: '1px solid var(--neutral-200)', borderRadius: 'var(--radius)' }}>
              <summary style={{ cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-600)' }}>Advanced attribute mapping</summary>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '10px', marginTop: '10px' }}>
                {[
                  ['email_attr', 'Email attribute', 'LDAP email attribute'],
                  ['display_name_attr', 'Display name attribute', 'LDAP display name attribute'],
                  ['department_attr', 'Department attribute', 'LDAP department attribute'],
                  ['external_id_attr', 'External ID attribute', 'LDAP external ID attribute'],
                ].map(([field, label, ariaLabel]) => (
                  <label htmlFor={`settings-ldap-${field}`} key={field} style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
                    {label}
                    <input aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id={`settings-ldap-${field}`} aria-label={ariaLabel} type="text" value={ldapForm[field as keyof LdapSettingsResponse] as string}
                      onChange={(e) => setLdapForm({ ...ldapForm, [field]: e.target.value })}
                      style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
                  </label>
                ))}
              </div>
            </details>
          </div>

          {!ldapForm.enabled && (
            <p style={{ margin: '12px 0 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Enable directory authentication to test the connection</p>
          )}
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px' }}>
            <details className="settings-advanced" open={ldapForm.ssl_verify === 'ca' || undefined}><summary>Advanced directory connection settings</summary><div className="settings-field-grid"><label htmlFor="settings-ldap-user-search-filter" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              User search filter
              <input aria-describedby="settings-ldap-user-search-filter-hint" aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-user-search-filter" aria-label="LDAP user search filter" type="text" value={ldapForm.user_search_filter}
                onChange={(e) => setLdapForm({ ...ldapForm, user_search_filter: e.target.value })}
                placeholder="(sAMAccountName={username})"
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
              <span style={{ color: 'var(--neutral-600)', lineHeight: 1.4 }}>Exactly one {'{username}'} placeholder — e.g. (sAMAccountName={'{username}'}) for AD, (uid={'{username}'}) for generic LDAP.</span>
            </label><span id="settings-ldap-user-search-filter-hint" style={HINT_STYLE}>Include exactly one username placeholder.</span><label htmlFor="settings-ldap-timeout-seconds" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px' }}>
              Timeout (seconds)
              <input aria-describedby="settings-ldap-timeout-seconds-hint" aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-timeout-seconds" aria-label="LDAP timeout seconds" type="number" step="any" required min="1" aria-valuetext={Number.isFinite(ldapForm.timeout_seconds) ? undefined : 'No value entered'} value={Number.isFinite(ldapForm.timeout_seconds) ? ldapForm.timeout_seconds : ''}
                onChange={(e) => setLdapForm({ ...ldapForm, timeout_seconds: e.target.value === '' ? NaN : Number(e.target.value) })}
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }} />
            </label><span id="settings-ldap-timeout-seconds-hint" style={HINT_STYLE}>Directory connection timeout in seconds.</span><label htmlFor="settings-ldap-custom-ca-bundle" style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', color: 'var(--neutral-500)', gap: '4px', gridColumn: '1 / -1' }}>
              Custom CA bundle (PEM)
              <textarea aria-describedby="settings-ldap-custom-ca-bundle-hint" aria-errormessage={ldapError ? 'settings-ldap-error' : undefined} id="settings-ldap-custom-ca-bundle" aria-label="LDAP custom CA bundle" data-validation-message="Enter PEM certificate contents when custom CA verification is selected." value={ldapForm.ssl_ca_bundle || ''}
                onChange={(e) => setLdapForm({ ...ldapForm, ssl_ca_bundle: e.target.value })}
                disabled={ldapForm.ssl_verify !== 'ca'}
                placeholder="PEM certificate(s), one or more -----BEGIN CERTIFICATE----- blocks"
                rows={5} required
                style={{ padding: '8px 10px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.8rem', fontFamily: 'monospace', resize: 'vertical', opacity: ldapForm.ssl_verify === 'ca' ? 1 : 0.55 }} />
            </label><span id="settings-ldap-custom-ca-bundle-hint" style={HINT_STYLE}>PEM certificate contents. Required with custom CA verification.</span></div></details>
<ActionButton variant="primary" style={{ marginTop: 12 }} busy={savingLdap} type="button" role="button" aria-label="Save LDAP settings"
              onClick={saveLdapSettings} disabled={savingLdap || !loadedSections.ldap}>
              Save Directory Settings
            </ActionButton>
            <span style={{ fontSize: '0.8rem' }}>Tests saved settings. Save or reset changes first.</span>
            <ActionButton variant="secondary" style={{ marginTop: 12 }} busy={testingLdap} type="button" role="button" aria-label="Test directory connection"
              title="Tests saved directory settings. Save or reset changes first." onClick={testLdapConnection} disabled={!loadedSections.ldap || !ldapForm.enabled || testingLdap || savingLdap || !!serviceDirty.ldap}>
              Test connection
            </ActionButton>
          </div>
        <ActionButton variant="quiet" type="button" disabled={!serviceDirty.ldap} onClick={() => { clearValidation('ldap'); setLdapForm({ ...baselines.current.ldap }); setLdapSaved(false); setLdapError(null); }}>Reset directory changes</ActionButton></fieldset>
</div></section>
      </div>


    </div>
  );
}
export default IntegrationSettings;
