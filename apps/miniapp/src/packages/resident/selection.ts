import { authenticatedUserId } from '../../core/session';
import { readStored, writeStored, removeStored } from './storage';
export function getSelectedBindingId(): string | null {
  if (!authenticatedUserId()) return null;
  return readStored('resident-house', '', (value) =>
    typeof value === 'string' && value.length > 0 ? value : undefined,
  );
}
export function setSelectedBindingId(bindingId: string | null): void {
  if (!authenticatedUserId()) return;
  try {
    if (bindingId) writeStored('resident-house', '', bindingId);
    else removeStored('resident-house', '');
  } catch {
    /* A preference must not block a verified operation. */
  }
}
