import { history } from '@umijs/max';
import { useSyncExternalStore } from 'react';

let unblock: (() => void) | undefined;
const address = () => history.location.pathname + history.location.search;
const subscribe = (listener: () => void) => history.listen(listener);

export function navigate(to: string, replace = false) {
  if (replace) history.replace(to);
  else history.push(to);
}

export function setNavigationGuard(guard?: (action: () => void) => void) {
  unblock?.();
  unblock = undefined;
  if (!guard) return;

  const release = history.block((transition) => {
    guard(() => {
      // A confirmation from an unmounted workspace must not move the new session.
      if (unblock !== release) return;
      release();
      unblock = undefined;
      transition.retry();
    });
  });
  unblock = release;
}

export function useAddress() {
  return useSyncExternalStore(subscribe, address, () => '/');
}
