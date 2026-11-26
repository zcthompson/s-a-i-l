/** Local outline icons: decorative, theme-aware and independent of emoji fonts. */
const paths: Record<string, string> = {
  '⚠️': 'M12 3 2 21h20ZM12 9v5m0 3h.01',
  '🎫': 'M3 5h18v5a2 2 0 0 0 0 4v5H3v-5a2 2 0 0 0 0-4ZM15 5v3m0 3v2m0 3v3',
  'ℹ️': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M12 11v6m0-10h.01',
  '📄': 'M5 2h9l5 5v15H5ZM14 2v6h5M8 12h8m-8 4h8',
  '🏠': 'M3 10 12 3l9 7v11h-6v-7H9v7H3Z',
  '🏢': 'M3 21h18M5 21V3h14v18M8 7h1m6 0h1M8 11h1m6 0h1M8 15h1m6 0h1M11 21v-4h2v4',
  '📋': 'M8 5H5v16h14V5h-3M8 3h8v4H8ZM8 11h8m-8 4h8',
  '➕': 'M12 4v16M4 12h16',
  '🧭': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M16 8l-3 5-5 3 3-5Z',
  '📥': 'M12 3v12m-4-4 4 4 4-4M4 14v7h16v-7',
  '📤': 'M12 16V3m-4 4 4-4 4 4M4 14v7h16v-7',
  '💬': 'M3 3h18v14H9l-6 4Z',
  '📝': 'M14 4H4v17h16V11M10 14l1-4 8-8 3 3-8 8Z',
  '🔔': 'M6 9a6 6 0 0 1 12 0v7l2 2H4l2-2ZM10 21h4',
  '⚙️': 'M3 6h4m4 0h10M3 12h10m4 0h4M3 18h6m4 0h8M7 4h4v4H7ZM13 10h4v4h-4ZM9 16h4v4H9Z',
  '🎨': 'M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6M10 15v6',
  '🛡️': 'M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6ZM8 12l3 3 5-6',
  '👥': 'M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M2 21v-3a7 7 0 0 1 14 0v3M17 4a4 4 0 0 1 0 8m2 3a6 6 0 0 1 3 6',
  '🔗': 'M10 14l4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2 1 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0',
  '📊': 'M4 3v18h18M8 17v-5m5 5V8m5 9V4',
  '🔑': 'M8 3a5 5 0 1 0 0 10 5 5 0 0 0 0-10M12 12l9 9m-5-5 3-3m-1 5 3-3',
};
export function SectionIcon({ name, size = 20 }: { name: string; size?: number }) {
  return <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, verticalAlign: 'middle' }}><path d={paths[name] || paths['📋']} /></svg>;
}
