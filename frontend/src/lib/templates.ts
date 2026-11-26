// AI use-case templates — served by the backend (backend/templates.py) via
// GET /api/bulk/templates/. This module maps the wire shape to the
// TemplateData shape the UI uses and caches the fetch at module scope.

import { api } from './api';
import type { TemplateInfo } from '../types/use_case';

export interface TemplateData {
  id: string;
  name: string;
  icon: string;
  department: string;
  description: string;
  title: string;
  goals: string[];
  challenges: string[];
  painPoints: string[];
  impactCategory: string;
  impactDescription: string;
  timeline: string;
}

function toTemplateData(id: string, info: TemplateInfo): TemplateData {
  return {
    id,
    name: info.name,
    icon: info.icon || '📄',
    department: info.default_department || '',
    description: info.description || '',
    title: info.default_title || info.name,
    goals: info.default_goals || [],
    challenges: info.default_challenges || [],
    painPoints: info.default_pain_points || [],
    impactCategory: info.impact_category || '',
    impactDescription: info.impact_description || '',
    timeline: info.timeline || '',
  };
}

let _cache: Promise<TemplateData[]> | null = null;

/** Load all templates from the API (cached for the session).
 *
 * The template registry is NOT user-scoped (every authenticated user sees
 * the same 11 templates — `GET /api/bulk/templates/` requires auth but has
 * no per-customer/per-role filtering), so a session-level cache is safe
 * across logout/login. If templates ever become identity-scoped, key the
 * cache by the authenticated identity and add an invalidation hook.
 */
export function loadTemplates(): Promise<TemplateData[]> {
  if (!_cache) {
    _cache = api
      .templates()
      .then((res) =>
        Object.entries(res.templates || {}).map(([id, info]) => toTemplateData(id, info)),
      )
      .catch((err) => {
        _cache = null; // allow a retry on the next call
        throw err;
      });
  }
  return _cache;
}

/** Look up one template by id (from the cached load). */
export async function getTemplateById(id: string): Promise<TemplateData | undefined> {
  const all = await loadTemplates();
  return all.find((t) => t.id === id);
}

/** All available template ids (from the cached load). */
export async function templateIds(): Promise<string[]> {
  const all = await loadTemplates();
  return all.map((t) => t.id);
}
