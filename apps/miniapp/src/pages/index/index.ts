import {
  currentCredential,
  restoreSession,
  safeReturn,
  sessionRevision,
} from '../../core/session';
import { ApiError, errorText } from '../../core/request';
import { discoverIdentity } from '../../core/identities';
import { go, returnAfterLogin } from '../../ui/navigation';
Page({
  data: { loading: true, error: '', signed: false },
  epoch: 0,
  returnTo: '',
  onLoad(options: Record<string, string | undefined>) {
    this.returnTo = safeReturn(options.return_to);
  },
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
  phones() {
    go('phones');
  },
  async restore() {
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '', signed: !!currentCredential() });
    if (!currentCredential()) {
      go('home');
      return;
    }
    try {
      await restoreSession();
      if (epoch !== this.epoch) return;
      const session = sessionRevision();
      if (this.returnTo !== '/pages/phones/index')
        await discoverIdentity(
          () => epoch === this.epoch && session === sessionRevision(),
        );
      if (epoch === this.epoch && session === sessionRevision())
        returnAfterLogin(this.returnTo);
    } catch (error) {
      if (epoch !== this.epoch) return;
      if (error instanceof ApiError && error.status === 401) {
        go('home');
        return;
      }
      this.setData({ error: errorText(error), signed: !!currentCredential() });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
});
