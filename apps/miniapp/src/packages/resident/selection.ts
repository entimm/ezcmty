import { API_BASE_URL } from '../../config';
import { currentCredential, onSessionReset } from '../../core/session';

const prefix = 'xlife:' + API_BASE_URL + ':resident-house:';
let owner: string | undefined;

function key(): string | null {
  owner = currentCredential()?.userId;
  return owner ? prefix + owner : null;
}
onSessionReset(() => {
  if (owner) {
    try {
      wx.removeStorageSync(prefix + owner);
    } catch {
      /* No in-memory selection is retained. */
    }
  }
  owner = undefined;
});

export function getSelectedBindingId(): string | null {
  const storageKey = key();
  if (!storageKey) return null;
  try {
    const value = wx.getStorageSync(storageKey) as unknown;
    return typeof value === 'string' && value.length > 0 ? value : null;
  } catch {
    return null;
  }
}
export function setSelectedBindingId(bindingId: string | null): void {
  const storageKey = key();
  if (!storageKey) return;
  try {
    if (bindingId) wx.setStorageSync(storageKey, bindingId);
    else wx.removeStorageSync(storageKey);
  } catch {
    /* A convenience preference must not block a verified business operation. */
  }
}
