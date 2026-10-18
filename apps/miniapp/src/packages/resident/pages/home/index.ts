import {
  currentCredential,
  onSessionReset,
  requireSession,
  restoreSession,
} from '../../../../auth/resident';
import { errorText } from '../../../../shared/http/client';
import { claimPage, residentHome } from '../../../../shared/wechat/ui';
import { bindings, claims } from '../../api';
import { detailUrl } from '../../presentation';
import { Binding } from '../../types';
Page({
  data: {
    loading: false,
    error: '',
    signedIn: false,
    houses: [] as Binding[],
    houseCount: 0,
    pendingCount: 0,
  },
  epoch: 0,
  off: () => {},
  onLoad() {
    this.off = onSessionReset(() => {
      this.epoch++;
      this.setData({
        signedIn: false,
        houses: [],
        houseCount: 0,
        pendingCount: 0,
      });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
  },
  onShow() {
    void this.load();
  },
  async onPullDownRefresh() {
    try {
      await this.load();
    } finally {
      wx.stopPullDownRefresh();
    }
  },
  async load() {
    const epoch = ++this.epoch;
    this.setData({ signedIn: !!currentCredential(), error: '' });
    if (!currentCredential()) return;
    this.setData({ loading: true });
    try {
      await restoreSession();
      const [homes, pending] = await Promise.all([
        bindings(1, 'active'),
        claims(1, 'pending'),
      ]);
      if (epoch !== this.epoch) return;
      this.setData({
        houses: homes.items.slice(0, 3),
        houseCount: homes.total,
        pendingCount: pending.total,
      });
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({
          error: errorText(error),
          signedIn: !!currentCredential(),
        });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  login() {
    requireSession(residentHome);
  },
  claim() {
    if (requireSession(claimPage)) wx.navigateTo({ url: claimPage });
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: detailUrl('house', event.currentTarget.dataset.id) });
  },
  houses() {
    wx.navigateTo({ url: '/packages/resident/pages/houses/index' });
  },
  claims() {
    wx.navigateTo({ url: '/packages/resident/pages/claims/index' });
  },
  profile() {
    wx.navigateTo({ url: '/packages/resident/pages/profile/index' });
  },
  bills() {
    const url = '/packages/resident/pages/bills/index';
    if (requireSession(url)) wx.navigateTo({ url });
  },
});
