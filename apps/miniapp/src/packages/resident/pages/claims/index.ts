import { onSessionReset, requireSession } from '../../../../auth/resident';
import { errorText } from '../../../../shared/http/client';
import { claimPage, formatTime } from '../../../../shared/wechat/ui';
import { claims } from '../../api';
import { claimLabels, detailUrl } from '../../presentation';
import { Claim } from '../../types';
interface Row extends Claim {
  label: string;
  display_time: string;
}
Page({
  data: { loading: true, error: '', items: [] as Row[], total: 0, page: 1 },
  off: () => {},
  epoch: 0,
  onLoad() {
    this.off = onSessionReset(() => {
      this.epoch++;
      this.setData({ items: [], total: 0 });
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
  async load(more = false) {
    if (!requireSession('/packages/resident/pages/claims/index')) {
      this.setData({ loading: false });
      return;
    }
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    try {
      const page = more ? this.data.page + 1 : 1;
      const result = await claims(page);
      if (epoch !== this.epoch) return;
      const items = result.items.map((item) => ({
        ...item,
        label: claimLabels[item.status],
        display_time: formatTime(item.created_at),
      }));
      this.setData({
        items: more ? [...this.data.items, ...items] : items,
        total: result.total,
        page,
      });
    } catch (error) {
      if (epoch === this.epoch) this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  retry() {
    void this.load();
  },
  more() {
    if (!this.data.loading) void this.load(true);
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: detailUrl('claim', event.currentTarget.dataset.id) });
  },
  claim() {
    wx.navigateTo({ url: claimPage });
  },
});
