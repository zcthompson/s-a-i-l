import { useEffect, useLayoutEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

type Position = { windowX: number; windowY: number; mainX: number; mainY: number };
const TOP: Position = { windowX: 0, windowY: 0, mainX: 0, mainY: 0 };
const MAX_ENTRIES = 100;

/** Identifies a destination without using filters or drafts as navigation. */
function destination(search: string): string {
  const p = new URLSearchParams(search);
  return JSON.stringify([
    p.get('view') || 'dashboard', p.get('customer'), p.get('area'),
    p.get('customer_uc'), p.get('uc'), p.get('source'), p.get('import'),
  ]);
}

/** Keep positions in memory only; never put account data in persistent keys. */
export function useWorkspaceScroll(mainRef: RefObject<HTMLElement>): void {
  const location = useLocation();
  const navigation = useNavigationType();
  const positions = useRef(new Map<string, Position>());
  const currentKey = useRef(location.key);
  const previousDestination = useRef(destination(location.search));
  const first = useRef(true);
  const cancelRestore = useRef<() => void>(() => {});

  useEffect(() => {
    const original = window.history.scrollRestoration;
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';
    return () => { if ('scrollRestoration' in window.history) window.history.scrollRestoration = original; };
  }, []);

  useEffect(() => {
    const main = mainRef.current;
    const remember = () => {
      const position = { windowX: window.scrollX, windowY: window.scrollY, mainX: main?.scrollLeft ?? 0, mainY: main?.scrollTop ?? 0 };
      positions.current.set(currentKey.current, position);
      if (positions.current.size > MAX_ENTRIES) {
        const oldest = positions.current.keys().next().value;
        if (oldest !== undefined) positions.current.delete(oldest);
      }
    };
    const stop = () => cancelRestore.current();
    window.addEventListener('scroll', remember, { passive: true });
    main?.addEventListener('scroll', remember, { passive: true });
    window.addEventListener('wheel', stop, { passive: true });
    window.addEventListener('touchstart', stop, { passive: true });
    window.addEventListener('pointerdown', stop, { passive: true });
    window.addEventListener('keydown', stop);
    return () => {
      cancelRestore.current();
      window.removeEventListener('scroll', remember);
      main?.removeEventListener('scroll', remember);
      window.removeEventListener('wheel', stop);
      window.removeEventListener('touchstart', stop);
      window.removeEventListener('pointerdown', stop);
      window.removeEventListener('keydown', stop);
    };
  }, [mainRef]);

  useLayoutEffect(() => {
    const main = mainRef.current;
    const nextDestination = destination(location.search);
    const previous = positions.current.get(currentKey.current) ?? {
      windowX: window.scrollX, windowY: window.scrollY, mainX: main?.scrollLeft ?? 0, mainY: main?.scrollTop ?? 0,
    };
    cancelRestore.current();
    const target = first.current ? null : navigation === 'POP'
      ? positions.current.get(location.key) ?? TOP
      : nextDestination === previousDestination.current ? previous : TOP;
    first.current = false;
    previousDestination.current = nextDestination;
    currentKey.current = location.key;
    if (!target) return;
    positions.current.set(location.key, target);

    let observer: ResizeObserver | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let frame = 0;
    const cancel = () => {
      observer?.disconnect();
      if (timer) clearTimeout(timer);
      if (frame) cancelAnimationFrame(frame);
      cancelRestore.current = () => {};
    };
    const restore = () => {
      if (main && (main.scrollLeft !== target.mainX || main.scrollTop !== target.mainY)) {
        if (typeof main.scrollTo === 'function') main.scrollTo({ left: target.mainX, top: target.mainY, behavior: 'instant' });
        else { main.scrollLeft = target.mainX; main.scrollTop = target.mainY; }
      }
      if (window.scrollX !== target.windowX || window.scrollY !== target.windowY) {
        window.scrollTo({ left: target.windowX, top: target.windowY, behavior: 'instant' });
      }
      const reached = Math.abs(window.scrollY - target.windowY) < 2 && Math.abs(window.scrollX - target.windowX) < 2
        && (!main || (Math.abs(main.scrollTop - target.mainY) < 2 && Math.abs(main.scrollLeft - target.mainX) < 2));
      if (reached) cancel();
    };
    cancelRestore.current = cancel;
    // Reapply while lazy content grows, but stop as soon as the user interacts.
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(restore);
      if (main) observer.observe(main);
      observer.observe(document.body);
    }
    timer = setTimeout(cancel, 5000);
    frame = requestAnimationFrame(restore);
    restore();
    return cancel;
  }, [location.key, location.search, navigation, mainRef]);
}
