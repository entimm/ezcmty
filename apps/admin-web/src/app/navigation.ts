import { useSyncExternalStore } from 'react';

let accepted = '';
let guard: ((action: () => void) => void) | undefined;
let shouldBlock: (() => boolean) | undefined;
let acceptedIndex = 0;
let restore: (() => void) | undefined;
const listeners = new Set<() => void>();
const address = () => window.location.pathname + window.location.search;
function publish() {
  accepted = address();
  listeners.forEach((listener) => listener());
}
export function navigate(to: string, replace = false) {
  if (!replace) acceptedIndex++;
  window.history[replace ? 'replaceState' : 'pushState'](
    { xlifeNavigationIndex: acceptedIndex },
    '',
    to,
  );
  publish();
}
export function setNavigationGuard(
  value?: (action: () => void) => void,
  blocked?: () => boolean,
) {
  guard = value;
  shouldBlock = blocked;
}
function subscribe(listener: () => void) {
  if (!listeners.size) {
    accepted = address();
    acceptedIndex =
      typeof window.history.state?.xlifeNavigationIndex === 'number'
        ? window.history.state.xlifeNavigationIndex
        : 0;
    window.history.replaceState(
      { xlifeNavigationIndex: acceptedIndex },
      '',
      accepted,
    );
  }
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener('popstate', onBack);
  return () => {
    listeners.delete(listener);
    if (!listeners.size) window.removeEventListener('popstate', onBack);
  };
}
function onBack() {
  if (restore) {
    const ready = restore;
    restore = undefined;
    ready();
    return;
  }
  const target = address();
  const targetIndex = window.history.state?.xlifeNavigationIndex as
    number | undefined;
  if (guard && shouldBlock?.() && accepted !== target) {
    if (typeof targetIndex === 'number' && targetIndex !== acceptedIndex) {
      const delta = targetIndex - acceptedIndex;
      restore = () => guard?.(() => window.history.go(delta));
      window.history.go(-delta);
    } else {
      window.history.replaceState(
        { xlifeNavigationIndex: acceptedIndex },
        '',
        accepted,
      );
      guard(() => navigate(target));
    }
  } else {
    acceptedIndex =
      typeof targetIndex === 'number' ? targetIndex : acceptedIndex;
    publish();
  }
}
export function useAddress() {
  return useSyncExternalStore(subscribe, address, () => '/');
}
