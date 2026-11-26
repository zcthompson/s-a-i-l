/**
 * Mobius palette: pure unit tests (no WebGL).
 *
 * 0.2.14 item A: the on-black canvas category hexes are intentionally
 * luminous and DIVERGE from the DOM legend tokens (CATEGORY_STYLES
 * colors) so the WebGL surface reads bright against INK #050810. The
 * assertions pin the on-black values (valid literal hex per key, no
 * `var(` token, distinct hue per category).
 */
import { describe, it, expect } from 'vitest';
import { CATEGORY_STYLES } from '../src/lib/intelligenceGraph';
import { MOBIUS_CATEGORY_HEX, MOBIUS_STYLE_KEYS, MOBIUS_SURFACE, mobiusColor } from '../src/lib/mobiusPalette';

const EXPECTED_ON_BLACK_HEX = {
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

describe('mobius color map', () => {
  it('covers every CATEGORY_STYLES key with a literal hex (no var() tokens)', () => {
    expect(MOBIUS_STYLE_KEYS.sort()).toEqual(Object.keys(CATEGORY_STYLES).sort());
    Object.keys(CATEGORY_STYLES).forEach((k) => {
      const hex = (MOBIUS_CATEGORY_HEX as Record<string, string>)[k];
      expect(hex).toMatch(/^#[0-9a-f]{6}$/i);
      expect(hex).not.toContain('var(');
    });
  });

  it('gives each data domain a DISTINCT on-black hex (no two domains share a hue)', () => {
    const keys = ['customer', 'domain', 'technology', 'use_case', 'sales_note', 'assessment', 'assessment_generic', 'sales_evaluation', 'risk', 'opportunity'];
    const seen = new Set<string>();
    keys.forEach((k) => {
      const hex = (MOBIUS_CATEGORY_HEX as Record<string, string>)[k];
      expect(seen.has(hex), `${k} hex ${hex} collides with another category`).toBe(false);
      seen.add(hex);
    });
  });

  it('pins the luminous on-black palette and warm core chrome', () => {
    expect(MOBIUS_CATEGORY_HEX).toEqual(EXPECTED_ON_BLACK_HEX);
    expect(MOBIUS_SURFACE.coreNode).toBe('#fdf7e6');
    expect(MOBIUS_SURFACE.coreGlow).toBe('#f6d98c');
  });

  it('falls back safely for an unknown category', () => {
    expect(mobiusColor('nonsense')).toBe(MOBIUS_CATEGORY_HEX.domain);
  });
});
