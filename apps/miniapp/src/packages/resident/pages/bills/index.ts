import { onSessionReset, requireSession } from '../../../../auth/resident';
import { errorText } from '../../../../shared/http/client';
import { bindings } from '../../api';
import { bills } from '../../billing/api';
import { availability, money } from '../../billing/presentation';
import { ResidentBill } from '../../billing/types';
import { Binding } from '../../types';
interface Row extends ResidentBill {
  amount: string;
  hint: string;
}
Page({
  data: {
    loading: false,
    error: '',
    houses: [] as Binding[],
    houseId: '',
    scope: 'outstanding',
    items: [] as Row[],
    total: 0,
    page: 1,
  },
  epoch: 0,
  off: () => {},
  onLoad(options) {
    this.setData({ houseId: options.house_id || '' });
    this.off = onSessionReset(() => {
      this.epoch++;
      this.setData({
        houses: [],
        houseId: '',
        items: [],
        total: 0,
        loading: false,
        error: '',
      });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
  },
  onShow() {
    void this.loadHouses();
  },
  async loadHouses() {
    if (!requireSession('/packages/resident/pages/bills/index')) return;
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '', items: [] });
    try {
      const houses: Binding[] = [];
      let page = 1;
      while (true) {
        const result = await bindings(page, 'active');
        if (epoch !== this.epoch) return;
        houses.push(...result.items.filter((item) => item.effective_enabled));
        if (page * result.page_size >= result.total) break;
        page++;
      }
      const houseId = houses.some((item) => item.house_id === this.data.houseId)
        ? this.data.houseId
        : houses.length === 1
          ? houses[0].house_id
          : '';
      this.setData({ houses, houseId, loading: false });
      if (houseId) await this.load();
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({ error: errorText(error), loading: false });
    }
  },
  choose(event: WechatMiniprogram.TouchEvent) {
    this.epoch++;
    this.setData({
      houseId: event.currentTarget.dataset.id,
      scope: 'outstanding',
      page: 1,
      items: [],
      total: 0,
    });
    void this.load();
  },
  scope(event: WechatMiniprogram.TouchEvent) {
    this.setData({
      scope: event.currentTarget.dataset.scope,
      items: [],
      total: 0,
    });
    void this.load();
  },
  async load(more = false) {
    if (
      !this.data.houseId ||
      !requireSession('/packages/resident/pages/bills/index')
    )
      return;
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    try {
      const page = more ? this.data.page + 1 : 1;
      const selected = this.data.houses.find(
        (item) => item.house_id === this.data.houseId,
      );
      if (!selected) return;
      const result = await bills(selected.id, page, this.data.scope);
      if (epoch !== this.epoch) return;
      const items = result.items.map((item) => ({
        ...item,
        amount: money(item.outstanding_cents),
        hint: availability[item.payment_availability],
      }));
      this.setData({
        items: more ? [...this.data.items, ...items] : items,
        total: result.total,
        page,
      });
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({ error: errorText(error), items: [], total: 0 });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  more() {
    if (!this.data.loading) void this.load(true);
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({
      url:
        '/packages/resident/pages/bill-detail/index?id=' +
        event.currentTarget.dataset.id,
    });
  },
});
