import {
  currentCredential,
  logout,
  onSessionReset,
} from '../../../../auth/resident';
import {
  confirm,
  residentHome,
  toastError,
} from '../../../../shared/wechat/ui';
Page({
  data: { signedIn: false, busy: false },
  off: () => {},
  onLoad() {
    this.off = onSessionReset(() => this.setData({ signedIn: false }));
  },
  onUnload() {
    this.off();
  },
  onShow() {
    this.setData({ signedIn: !!currentCredential() });
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: event.currentTarget.dataset.url });
  },
  login() {
    wx.navigateTo({
      url:
        '/pages/login/index?return_to=' +
        encodeURIComponent('/packages/resident/pages/profile/index'),
    });
  },
  async logout() {
    if (
      this.data.busy ||
      !(await confirm('退出登录', '退出后可随时通过微信重新登录。'))
    )
      return;
    this.setData({ busy: true });
    try {
      await logout();
    } catch (error) {
      toastError(error);
    } finally {
      this.setData({ busy: false });
      wx.reLaunch({ url: residentHome });
    }
  },
});
