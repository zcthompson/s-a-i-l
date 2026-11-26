/**
 * Component tests for GapAnalysis (Phase 3 — readiness dimensions ×
 * environment factors matrix). Deterministic color-rule checks against
 * the documented rule: green when the environment factor score is 70+
 * or at/above the dimension score, amber when within 15 points below
 * the dimension score, red otherwise. Plain assertions — the project
 * has no @testing-library/jest-dom setup.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { GapAnalysis } from '../src/components/GapAnalysis';

// Vitest here runs without globals, so @testing-library/react's automatic
// cleanup does not register itself — clean up between tests manually
// (same pattern as F5CustomerUrlSync.test.tsx).
afterEach(() => {
  cleanup();
});

describe('GapAnalysis component - empty state', () => {
  it('renders empty state when readiness_dimensions is absent', () => {
    render(
      <GapAnalysis
        readiness_dimensions={undefined}
        environment_factors={undefined}
        gaps={undefined}
      />
    );

    expect(screen.getByText(/No readiness dimensions data available/i)).toBeTruthy();
  });

  it('renders empty state when environment_factors is absent', () => {
    render(
      <GapAnalysis
        readiness_dimensions={{ strategic_fit: 80 }}
        environment_factors={undefined}
        gaps={undefined}
      />
    );

    expect(screen.getByText(/No environment factors data available/i)).toBeTruthy();
  });
});

describe('GapAnalysis component - color rule', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('applies green/amber/red per the documented rule', () => {
    // single dimension row (80) × three factors:
    //   software_completeness 68: 80-68=12 ≤ 15 and <70 → amber
    //   hardware_currency     40: 80-40=40 > 15 and <70 → red
    //   vendor_diversity      90: ≥70                    → green
    render(
      <GapAnalysis
        readiness_dimensions={{ strategic_fit: 80 }}
        environment_factors={{
          software_completeness: 68,
          hardware_currency: 40,
          vendor_diversity: 90,
        }}
        gaps={undefined}
      />
    );

    expect(screen.getByText('Readiness Matrix')).toBeTruthy();
    expect(
      screen.getByRole('button', { name: /Gap detail for strategic_fit vs software_completeness/i }).style.background,
    ).toBe('var(--status-warning)');
    expect(
      screen.getByRole('button', { name: /Gap detail for strategic_fit vs hardware_currency/i }).style.background,
    ).toBe('var(--status-negative)');
    expect(
      screen.getByRole('button', { name: /Gap detail for strategic_fit vs vendor_diversity/i }).style.background,
    ).toBe('var(--status-positive)');
  });

  it('renders one row per dimension with a score, skipping absent dimensions', () => {
    render(
      <GapAnalysis
        readiness_dimensions={{ strategic_fit: 80, risk_tolerance: 61 }}
        environment_factors={{ software_completeness: 82 }}
        gaps={undefined}
      />
    );

    expect(screen.getByText('strategic_fit')).toBeTruthy();
    expect(screen.getByText('risk_tolerance')).toBeTruthy();
    // absent dimensions (e.g. technical_feasibility) render no row
    expect(screen.queryByText('technical_feasibility')).toBeNull();
    // one cell per dimension row: 2 dimensions × 1 factor = 2 cells
    expect(screen.getAllByText('82.0/100').length).toBe(2);
  });
});

describe('GapAnalysis component - gap entries + drill-down', () => {
  const mockGaps: Array<{
    category: string;
    severity: 'high' | 'medium' | 'low';
    description: string;
    readiness_dimension?: string;
    environment_factor?: string;
  }> = [
    {
      category: 'Security',
      severity: 'high',
      description: 'Potential vulnerability',
      readiness_dimension: 'strategic_fit',
      environment_factor: 'software_completeness',
    },
  ];

  it('shows a gap-count badge in the matching cell', () => {
    render(
      <GapAnalysis
        readiness_dimensions={{ strategic_fit: 80 }}
        environment_factors={{ software_completeness: 82 }}
        gaps={mockGaps}
      />
    );

    expect(screen.getByText(/⚠ 1 gap\(s\)/i)).toBeTruthy();
  });

  it('shows the cell detail panel (scores + matching gaps) when a cell is clicked', () => {
    render(
      <GapAnalysis
        readiness_dimensions={{ strategic_fit: 80 }}
        environment_factors={{ software_completeness: 82 }}
        gaps={mockGaps}
      />
    );

    fireEvent.click(
      screen.getByRole('button', { name: /Gap detail for strategic_fit vs software_completeness/i }),
    );

    expect(screen.getByText(/strategic_fit × software_completeness/i)).toBeTruthy();
    expect(screen.getByText(/Potential vulnerability/i)).toBeTruthy();
    expect(screen.getByText(/high/i)).toBeTruthy();
  });

  it('shows a no-gap note when the selected cell has no matching gaps', () => {
    // vendor_diversity cell: the gap targets software_completeness, so this
    // cell has no matching gap entry.
    render(
      <GapAnalysis
        readiness_dimensions={{ strategic_fit: 80 }}
        environment_factors={{ vendor_diversity: 55 }}
        gaps={mockGaps}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: /Gap detail for strategic_fit vs vendor_diversity/i }),
    );

    expect(screen.getByText(/No specific gaps recorded for this cell/i)).toBeTruthy();
  });
});
