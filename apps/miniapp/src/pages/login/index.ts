import { login, currentCredential } from '../../auth/resident';
import { errorText } from '../../shared/http/client';
import { safeReturn } from '../../shared/wechat/ui';
Page({
  data: { busy: false, error: '' },
  target: '',
  onLoad(options) {
    this.target = safeReturn(options.return_to);
    if (currentCredential()) wx.redirectTo({ url: this.target });
  },
  async login() {
    if (this.data.busy) return;
    this.setData({ busy: true, error: '' });
    try {
      await login();
      wx.redirectTo({ url: this.target });
    } catch (error) {
      this.setData({ error: errorText(error) });
    } finally {
      this.setData({ busy: false });
    }
  },
});
