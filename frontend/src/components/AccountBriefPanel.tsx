/**
 * H6 — Account brief panel (Intelligence secondary rail).
 *
 * The preview is fetched ON MOUNT (no Generate button, no client-side
 * generation, no caching). The backend owns escaping: `markdown` is rendered
 * VERBATIM in a <pre> — no markdown dependency, no dangerouslySetInnerHTML.
 * Download buttons are visible to every panel reader; the export capability is
 * backend-authoritative, so a 403 detail is shown verbatim inline.
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { AccountBrief } from '../types/brief';

interface Props {
  customerId: number;
  userRole?: string;
}

const btn: React.CSSProperties = {
  padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)',
  borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600,
};

function saveBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.URL.revokeObjectURL(url);
}

export function AccountBriefPanel({ customerId }: Props) {
  const [brief, setBrief] = useState<AccountBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<'md' | 'pdf' | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBrief(null);
    setError(null);
    setDownloadError(null);
    setLoading(true);
    api.getAccountBrief(customerId)
      .then((b) => { if (!cancelled) setBrief(b); })
      .catch((e: any) => { if (!cancelled) setError(e?.message || 'Failed to load account brief'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [customerId]);

  const download = async (kind: 'md' | 'pdf') => {
    setDownloading(kind);
    setDownloadError(null);
    try {
      const blob = kind === 'md'
        ? await api.downloadAccountBriefMd(customerId)
        : await api.downloadAccountBriefPdf(customerId);
      saveBlob(blob, `account_brief_${customerId}.${kind}`);
    } catch (e: any) {
      setDownloadError(e?.message || 'Download failed');
    } finally {
      setDownloading(null);
    }
  };

  const s = brief?.source_snapshots;

  return (
    <div data-testid="account-brief-panel" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <h3 style={{ margin: 0 }}>Account Brief</h3>

      {loading && <div>Loading account brief…</div>}

      {error && (
        <div role="status" data-testid="account-brief-error" style={{ color: 'var(--danger, #b91c1c)', fontSize: '0.85rem' }}>
          {error}
        </div>
      )}

      {brief && s && (
        <>
          <div data-testid="account-brief-meta" style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
            <div>Generated {brief.generated_at} · {brief.calc_version}</div>
            <div>
              {s.technology_recorded} technologies · {s.notes_recorded} notes · {s.contacts_recorded} contacts · {s.activities_recorded} activities · {s.open_tasks} open tasks (recorded)
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button type="button" style={btn} data-testid="account-brief-download-md" disabled={downloading !== null} onClick={() => download('md')}>
              Download Markdown
            </button>
            <button type="button" style={btn} data-testid="account-brief-download-pdf" disabled={downloading !== null} onClick={() => download('pdf')}>
              Download PDF
            </button>
          </div>

          {downloadError && (
            <div role="status" data-testid="account-brief-download-error" style={{ fontSize: '0.85rem', color: 'var(--danger, #b91c1c)' }}>
              {downloadError}
            </div>
          )}

          <pre
            data-testid="account-brief-markdown"
            style={{
              margin: 0, padding: '12px', maxHeight: '600px', overflow: 'auto', whiteSpace: 'pre-wrap',
              background: 'var(--neutral-50, #f8fafc)', border: '1px solid var(--divider)',
              borderRadius: 'var(--radius)', fontSize: '0.8rem',
            }}
          >
            {brief.markdown}
          </pre>
        </>
      )}
    </div>
  );
}
