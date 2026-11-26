import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { useWorkspaceScroll } from '../src/lib/useWorkspaceScroll';

function Harness() {
  const mainRef = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  useWorkspaceScroll(mainRef);
  return <><button onClick={() => navigate('/?view=customers&customer=A&area=sales-notes')}>Open notes</button>
    <button onClick={() => navigate('/?view=customers&customer=A&area=customer-knowledge')}>Open knowledge</button>
    <button onClick={() => navigate('/?view=customers&customer=A&area=sales-notes&q=filter', { replace: true })}>Filter</button>
    <button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button>
    <main ref={mainRef} data-testid="main" /></>;
}
let windowY = 0;
beforeEach(() => {
  windowY = 0;
  vi.spyOn(window, 'scrollY', 'get').mockImplementation(() => windowY);
  vi.spyOn(window, 'scrollX', 'get').mockReturnValue(0);
  vi.spyOn(window, 'scrollTo').mockImplementation((options) => { windowY = typeof options === 'object' ? options.top ?? 0 : 0; });
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: function (this: HTMLElement, options: ScrollToOptions) {
    this.scrollTop = options.top ?? 0; this.scrollLeft = options.left ?? 0;
  } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); delete (HTMLElement.prototype as any).scrollTo; });
function move(y: number, mainY: number) {
  windowY = y;
  const main = screen.getByTestId('main');
  main.scrollTop = mainY;
  fireEvent.scroll(window);
  fireEvent.scroll(main);
}

describe('workspace scroll restoration', () => {
  it('starts new destinations at the top and restores Back/Forward positions', () => {
    render(<MemoryRouter initialEntries={['/?view=dashboard']}><Harness /></MemoryRouter>);
    move(300, 120);
    fireEvent.click(screen.getByText('Open notes'));
    expect(windowY).toBe(0);
    expect(screen.getByTestId('main').scrollTop).toBe(0);
    move(220, 90);
    fireEvent.click(screen.getByText('Open knowledge'));
    expect(windowY).toBe(0);
    fireEvent.click(screen.getByText('Back'));
    expect(windowY).toBe(220);
    expect(screen.getByTestId('main').scrollTop).toBe(90);
    fireEvent.click(screen.getByText('Back'));
    expect(windowY).toBe(300);
    expect(screen.getByTestId('main').scrollTop).toBe(120);
    fireEvent.click(screen.getByText('Forward'));
    expect(windowY).toBe(220);
  });

  it('retries a history position when lazy content grows and stops on user interaction', () => {
    let maxMain = 500;
    let observerCallback: (() => void) | undefined;
    let disconnected = false;
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { observerCallback = callback; disconnected = false; }
      observe() {}
      disconnect() { disconnected = true; }
    });
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: function (this: HTMLElement, options: ScrollToOptions) {
      this.scrollTop = Math.min(options.top ?? 0, maxMain);
    } });
    render(<MemoryRouter initialEntries={['/?view=dashboard']}><Harness /></MemoryRouter>);
    move(0, 240);
    fireEvent.click(screen.getByText('Open notes'));
    maxMain = 30;
    fireEvent.click(screen.getByText('Back'));
    expect(screen.getByTestId('main').scrollTop).toBe(30);
    maxMain = 500;
    observerCallback?.();
    expect(screen.getByTestId('main').scrollTop).toBe(240);
    expect(disconnected).toBe(true);
    move(0, 200);
    fireEvent.click(screen.getByText('Open notes'));
    maxMain = 20;
    fireEvent.click(screen.getByText('Back'));
    expect(screen.getByTestId('main').scrollTop).toBe(20);
    fireEvent.wheel(window);
    expect(disconnected).toBe(true);
    vi.unstubAllGlobals();
  });

  it('does not move keyboard focus when restoring scroll', () => {
    render(<MemoryRouter initialEntries={['/?view=dashboard']}><Harness /></MemoryRouter>);
    const button = screen.getByText('Open notes');
    button.focus();
    fireEvent.click(button);
    expect(document.activeElement).toBe(button);
  });

  it('preserves position when replacing filters within the same destination', () => {
    render(<MemoryRouter initialEntries={['/?view=customers&customer=A&area=sales-notes']}><Harness /></MemoryRouter>);
    move(150, 70);
    fireEvent.click(screen.getByText('Filter'));
    expect(windowY).toBe(150);
    expect(screen.getByTestId('main').scrollTop).toBe(70);
  });
});
