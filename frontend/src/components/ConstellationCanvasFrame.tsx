/**
 * ConstellationCanvasFrame — the theme-independent black visualization
 * surface of the Customer Intelligence Constellation.
 *
 * The constellation canvas is PERMANENTLY BLACK in both light and dark
 * application modes (CHANGELOG 0.1.3, items 6–7):
 * the graph is an intentional theme-independent surface while the
 * surrounding S-A-I-L UI follows normal light/dark behavior.
 *
 * Mechanism: everything inside this frame (the canvas and its overlays) is
 * authored with a BLACK-surface palette. Dark mode uses real theme tokens
 * (no root inversion), so the frame needs no filter in either theme.
 */
import { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Optional aria-label for the frame (it is a visual surface, not a
   *  widget — the canvas inside carries the interaction semantics). */
  'aria-label'?: string;
}

export function ConstellationCanvasFrame({ children, 'aria-label': ariaLabel }: Props) {
  return (
    <div
      aria-label={ariaLabel}
      style={{
        position: 'relative',
        borderRadius: 'var(--radius)',
        overflow: 'hidden',
        border: '1px solid var(--divider)',
      }}
    >
      {children}
    </div>
  );
}

export default ConstellationCanvasFrame;
