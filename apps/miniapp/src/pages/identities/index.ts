import {
  loadIdentities,
  selectIdentity,
  cancelIdentitySelection,
} from '../../core/identities';
import {
  currentCredential,
  requireSession,
  sessionRevision,
} from '../../core/session';
import { errorText, StaleSessionError } from '../../core/request';
import { entryFor } from '../../ui/business-navigation';
import { go, returnAfterLogin } from '../../ui/navigation';
Page({
  data: {
    loading: false,
    error: '',
    busy: '',
    items: [] as { id: string; display_name: string; supported: boolean }[],
  },
  epoch: 0,
  onShow() {
    void this.load();
  },
  onHide() {
    cancelIdentitySelection();
    this.epoch++;
    this.setData({ loading: false, busy: '' });
  },
  onUnload() {
    cancelIdentitySelection();
    this.epoch++;
  },
  async load() {
    if (!requireSession('/pages/identities/index')) return;
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    try {
      const items = await loadIdentities();
      if (epoch === this.epoch)
        this.setData({
          items: items.map((item) => ({
            id: item.id,
            display_name: item.display_name,
            supported: !!entryFor(item.type),
          })),
        });
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({ error: errorText(error), items: [] });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  async choose(event: WechatMiniprogram.TouchEvent) {
    if (this.data.busy) return;
    const id = String(event.currentTarget.dataset.id || '');
    const epoch = this.epoch;
    const session = sessionRevision();
    this.setData({ busy: id, error: '' });
    try {
      await selectIdentity(id);
      if (
        epoch === this.epoch &&
        session === sessionRevision() &&
        currentCredential()
      )
        returnAfterLogin('');
    } catch (error) {
      if (epoch === this.epoch && !(error instanceof StaleSessionError))
        this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ busy: '' });
    }
  },
  phones() {
    go('phones');
  },
});
