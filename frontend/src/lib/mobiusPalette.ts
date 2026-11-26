/**
 * Mobius palette — the single color source for the three.js Customer
 * Intelligence visualization (theme-independent dark surface, see
 * ConstellationCanvasFrame).
 *
 * three.js cannot resolve CSS custom properties: every color that reaches a
 * material must be a literal hex. `CATEGORY_STYLES` (lib/intelligenceGraph)
 * stores customer/domain as theme tokens (correct for the DOM legend); the
 * values here intentionally diverge from the DOM legend tokens: each hue is
 * tuned to remain luminous and distinct on the fixed INK #050810 stage. Keep
 * all nine semantic keys distinct; risk/opportunity in particular must never
 * collapse into a generic status color.
 */
import { CATEGORY_STYLES, CategoryKey } from './intelligenceGraph';

export const MOBIUS_CATEGORY_HEX: Record<CategoryKey, string> = {
  customer: '#fdf7e6',
  domain: '#a7b0c0',
  technology: '#4f8cff',
  use_case: '#9b6cff',
  sales_note: '#2dd4bf',
  assessment: '#f052a0',
  assessment_generic: '#facc15',
  sales_evaluation: '#fb923c',
  risk: '#ff4d5e',
  opportunity: '#4ade80',
};

export const MOBIUS_SURFACE = {
  ink: '#050810',
  panelBg: 'rgba(9, 13, 24, 0.92)',
  panelBorder: 'rgba(148, 163, 184, 0.18)',
  textPrimary: '#e7ecf5',
  textMuted: '#7d879b',
  coreNode: '#fdf7e6',
  coreGlow: '#f6d98c',
} as const;

/** Canvas/WebGL-safe hex for a node category (never a `var()` token). */
export function mobiusColor(category: string): string {
  const key = category as CategoryKey;
  return MOBIUS_CATEGORY_HEX[key] ?? MOBIUS_CATEGORY_HEX.domain;
}

/** Re-export so tests can assert the map covers every style key. */
export const MOBIUS_STYLE_KEYS = Object.keys(CATEGORY_STYLES) as CategoryKey[];
