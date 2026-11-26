// Pin the test clock's timezone so date formatting is deterministic on any host.
process.env.TZ = 'UTC';

// Vitest config — component/logic tests for the frontend.
// Kept separate from vite.config.ts so the app build config stays clean.
// Tests live in frontend/tests/ (outside tsconfig "include": ["src"]) so
// they are excluded from the `tsc --noEmit` / build gate; vitest transforms
// them via esbuild at run time.
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.{ts,tsx}'],
    // Cap worker parallelism: the full-suite dashboard/navigation tests race
    // the default 1000ms findBy timeout under high parallel load; 2 forks
    // keeps the suite fast and deterministic.
    pool: 'forks',
    poolOptions: { forks: { minForks: 1, maxForks: 2 } },
  },
});
