import {
  currentCredential,
  login,
  safeReturn,
  sessionRevision,
} from '../../core/session';
import { discoverIdentity } from '../../core/identities';
import { errorText, StaleSessionError } from '../../core/request';
import { go, returnAfterLogin } from '../../ui/navigation';
Page({
  data: { busy: false, error: '', infoOpen: false, signed: false },
  epoch: 0,
  visible: false,
  returnTo: '',
  operation: undefined as Promise<void> | undefined,
  onLoad(options: Record<string, string | undefined>) {
    this.returnTo = safeReturn(options.return_to || options.returnTo);
  },
  onShow() {
    this.visible = true;
    this.setData({ busy: !!this.operation, signed: !!currentCredential() });
    if (currentCredential() && !this.operation) void this.signIn();
  },
  onHide() {
    this.visible = false;
    this.epoch++;
    this.setData({ infoOpen: false });
  },
  onUnload() {
    this.visible = false;
    this.epoch++;
    this.operation = undefined;
  },
  async signIn() {
    if (!this.visible || this.data.busy || this.operation) return;
    const epoch = this.epoch;
    const authenticatedRevision =
      sessionRevision() + (currentCredential() ? 0 : 1);
    const operation = (currentCredential() ? Promise.resolve() : login()).then(
      async () => {
        if (authenticatedRevision !== sessionRevision())
          throw new StaleSessionError();
        if (!this.visible || epoch !== this.epoch)
          throw new StaleSessionError();
        if (this.returnTo !== '/pages/phones/index')
          await discoverIdentity(
            () =>
              this.visible &&
              epoch === this.epoch &&
              authenticatedRevision === sessionRevision(),
          );
      },
    );
    this.operation = operation;
    this.setData({ busy: true, error: '' });
    try {
      await operation;
      if (
        this.visible &&
        this.operation === operation &&
        authenticatedRevision === sessionRevision()
      )
        returnAfterLogin(this.returnTo);
    } catch (error) {
      if (
        this.visible &&
        this.operation === operation &&
        !(error instanceof StaleSessionError)
      )
        this.setData({
          error: errorText(error),
          signed: !!currentCredential(),
        });
    } finally {
      if (this.operation === operation) {
        this.operation = undefined;
        if (this.visible) this.setData({ busy: false });
      }
    }
  },
  phones() {
    go('phones');
  },
  browse() {
    if (!this.data.busy) go('home');
  },
  openInfo() {
    this.setData({ infoOpen: true });
  },
  closeInfo() {
    this.setData({ infoOpen: false });
  },
});
