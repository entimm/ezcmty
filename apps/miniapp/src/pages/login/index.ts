import { currentCredential, login, safeReturn } from '../../core/session';
import { errorText, StaleSessionError } from '../../core/request';
import { go, returnAfterLogin } from '../../ui/navigation';
Page({
  data: { busy: false, error: '', infoOpen: false },
  epoch: 0,
  visible: false,
  returnTo: '',
  operation: undefined as Promise<void> | undefined,
  onLoad(options: Record<string, string | undefined>) {
    this.returnTo = safeReturn(options.return_to || options.returnTo);
  },
  onShow() {
    this.visible = true;
    this.setData({ busy: !!this.operation });
    if (currentCredential() && !this.operation) returnAfterLogin(this.returnTo);
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
    const operation = login();
    this.operation = operation;
    this.setData({ busy: true, error: '' });
    try {
      await operation;
      if (this.visible && this.operation === operation)
        returnAfterLogin(this.returnTo);
    } catch (error) {
      if (
        this.visible &&
        this.operation === operation &&
        !(error instanceof StaleSessionError)
      )
        this.setData({ error: errorText(error) });
    } finally {
      if (this.operation === operation) {
        this.operation = undefined;
        if (this.visible) this.setData({ busy: false });
      }
    }
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
