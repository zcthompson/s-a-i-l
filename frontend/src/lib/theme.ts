/**
 * Theme + motion preference hooks for canvas-based components.
 *
 * The dark theme is a `html[data-theme='dark']` attribute (set by main.tsx on
 * boot and by Settings on change — NOT React state). Canvas components cannot
 * observe the attribute via CSS, so `useDarkMode` mirrors it into React state
 * with a MutationObserver; `useReducedMotion` mirrors the
 * `prefers-reduced-motion` media query so constellation pulses can be
 * disabled for users who ask for less motion.
 */
import { useEffect, useState } from 'react';

function currentDark(): boolean {
  if (typeof document === 'undefined') return false;
  return document.documentElement.getAttribute('data-theme') === 'dark';
}

export function useDarkMode(): boolean {
  const [dark, setDark] = useState<boolean>(currentDark);
  useEffect(() => {
    const el = document.documentElement;
    setDark(currentDark());
    if (typeof MutationObserver === 'undefined') return; // jsdom / minimal DOM
    const obs = new MutationObserver(() => setDark(currentDark()));
    obs.observe(el, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

function currentReduced(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(currentReduced);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener?.('change', onChange);
    return () => mq.removeEventListener?.('change', onChange);
  }, []);
  return reduced;
}
