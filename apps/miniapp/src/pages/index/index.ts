import { currentCredential, restoreSession } from '../../core/session';
import { ApiError, errorText } from '../../core/request';
import { go } from '../../ui/navigation';
Page({
  data: { loading: true, error: '' },
  epoch: 0,
  onShow() {
    void this.restore();
  },
  onHide() {
    this.epoch++;
    this.setData({ loading: false });
  },
  onUnload() {
    this.epoch++;
  },
  async restore() {
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    if (!currentCredential()) {
      go('home');
      return;
    }
    try {
      await restoreSession();
      if (epoch === this.epoch) go('home');
    } catch (error) {
      if (epoch !== this.epoch) return;
      if (error instanceof ApiError && error.status === 401) {
        go('home');
        return;
      }
      this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
});
