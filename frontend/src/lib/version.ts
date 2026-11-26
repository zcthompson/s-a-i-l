/**
 * Single frontend source of truth for the displayed application version.
 * UX audit #15 (2026-09-13): the version literal was hardcoded in TWO UI
 * surfaces (Sidebar footer, Settings ▸ About) and had already drifted from
 * the backend once. package.json is the frontend's canonical version holder
 * (aligned with the backend holders on every release), so read it once here
 * instead of hand-editing UI strings.
 */
import pkg from '../../package.json';

export const APP_VERSION: string = pkg.version;
