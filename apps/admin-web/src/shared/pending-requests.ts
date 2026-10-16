import type { AdminScope } from './admin-types';

const prefix = 'xlife2:submitted:';
const eventName = 'xlife2-submitted-change';
const accountPrefix = (scope: AdminScope, subject: string) =>
  `${prefix}${scope}:${subject}:`;
export function pendingSnapshot(scope: AdminScope, subject: string): string {
  const start = accountPrefix(scope, subject);
  try {
    return JSON.stringify(
      Object.keys(localStorage)
        .filter((key) => key.startsWith(start))
        .sort()
        .map((key) => localStorage.getItem(key)),
    );
  } catch {
    return '[]';
  }
}
export function subscribePending(listener: () => void) {
  window.addEventListener('storage', listener);
  window.addEventListener(eventName, listener);
  return () => {
    window.removeEventListener('storage', listener);
    window.removeEventListener(eventName, listener);
  };
}
export function savePending(
  scope: AdminScope,
  subject: string,
  key: string,
  value: object,
) {
  localStorage.setItem(
    `${accountPrefix(scope, subject)}${key}`,
    JSON.stringify(value),
  );
  window.dispatchEvent(new Event(eventName));
}
export function removePending(scope: AdminScope, subject: string, key: string) {
  localStorage.removeItem(`${accountPrefix(scope, subject)}${key}`);
  window.dispatchEvent(new Event(eventName));
}
export function clearPendingRequests(scope: AdminScope, subject: string) {
  const start = accountPrefix(scope, subject);
  try {
    Object.keys(localStorage)
      .filter((key) => key.startsWith(start))
      .forEach((key) => localStorage.removeItem(key));
  } catch {
    /* Storage restrictions must not prevent clearing the authenticated session. */
  }
  window.dispatchEvent(new Event(eventName));
}
