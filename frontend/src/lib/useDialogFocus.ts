import { useEffect, useRef, type RefObject } from 'react';

/** Focus stays in the active modal and returns to its opener after dismissal. */
export function useDialogFocus(ref: RefObject<HTMLElement>, identity: string | null, onClose: () => void) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    if (!identity || !dialog) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const controls = () => [...dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')].filter(el => !el.closest('[hidden], [aria-hidden="true"]'));
    const focusFirst = () => (controls()[0] || dialog).focus();
    focusFirst();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close.current(); }
      if (event.key !== 'Tab') return;
      const items = controls();
      const first = items[0]; const last = items[items.length - 1];
      if (!first) { event.preventDefault(); dialog.focus(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    const contain = (event: FocusEvent) => { if (event.target instanceof Node && !dialog.contains(event.target)) focusFirst(); };
    dialog.addEventListener('keydown', keydown);
    document.addEventListener('focusin', contain);
    return () => {
      dialog.removeEventListener('keydown', keydown);
      document.removeEventListener('focusin', contain);
      if (opener?.isConnected) opener.focus();
    };
  }, [ref, identity]);
}
