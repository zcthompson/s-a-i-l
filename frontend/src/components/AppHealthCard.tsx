import { useState, useEffect } from 'react';
import { api } from '../lib/api';

export function AppHealthCard() {
  const [status, setStatus] = useState<{ ok: boolean; message: string; latencyMs: number | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.appHealth()
      .then((res: any) => {
        if (!cancelled) {
          const healthy = res?.status === "healthy";
          setStatus({
            ok: healthy,
            message: healthy
              ? `${res.service ?? "sail"} ${res.version ? `v${res.version}` : ""} · healthy`.trim()
              : res?.message ?? "Backend did not report healthy",
            latencyMs: typeof res?.latencyMs === "number" ? res.latencyMs : null,
          });
        }
      })
      .catch((err: any) => {
        if (!cancelled) {
          setStatus({ ok: false, message: err?.message || 'Failed to reach backend', latencyMs: null });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: 20, marginBottom: 24 }}>
      <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>❤️ Application Health</h2>
      {status === null ? (
        <div style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Checking backend…</div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: '1.4rem' }}>{status.ok ? '🟢' : '🔴'}</span>
          <div>
            <div style={{ fontWeight: 600, color: status.ok ? 'var(--status-positive)' : 'var(--status-negative)', fontSize: '0.95rem' }}>
              {status.ok ? 'Backend API reachable' : 'Backend API unreachable'}
            </div>
            <div style={{ color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
              {status.message}
              {status.latencyMs != null ? ` · ${status.latencyMs} ms` : ''}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
