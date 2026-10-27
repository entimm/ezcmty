import { residentTabs } from '../../navigation';
import { requireIdentity as requireResidentIdentity } from '../../../../core/identities';
import { onContextReset } from '../../../../core/identities';
import { bindings, bills } from '../../api';
import { money } from '../../../../core/format';
import { ApiError, errorText } from '../../../../core/request';
import { getSelectedBindingId, setSelectedBindingId } from '../../selection';
import { currentCredential } from '../../../../core/session';
import { Binding, ResidentBill } from '../../types';
import { go, pageUrl } from '../../../../ui/navigation';
import { bindingView } from '../../presentation';
import { billPresentation } from '../payment-detail/view';

interface BillRow extends ResidentBill {
  month: string;
  amount: string;
  receivable: string;
  settled: string;
  paid: boolean;
  label: string;
  tone: string;
}
Page({
  data: {
    tabs: residentTabs,
    signed: false,
    loading: true,
    moreLoading: false,
    error: '',
    moreError: '',
    houses: [] as Binding[],
    selected: null as ReturnType<typeof bindingView> | null,
    pickerOpen: false,
    scope: 'outstanding' as 'outstanding' | 'all',
    items: [] as BillRow[],
    total: 0,
    page: 1,
    hasMore: false,
  },
  epoch: 0,
  visible: false,
  requestedHouseId: '',
  off: () => {},
  onLoad(options) {
    this.requestedHouseId = options.house_id || '';
    this.off = onContextReset(() => this.showGuest());
  },
  showGuest() {
    this.epoch++;
    this.setData({
      signed: false,
      selected: null,
      houses: [],
      items: [],
      total: 0,
      page: 1,
      hasMore: false,
      loading: false,
      moreLoading: false,
      pickerOpen: false,
      error: '',
      moreError: '',
    });
  },
  onShow() {
    if (
      currentCredential() &&
      !requireResidentIdentity(
        'resident',
        '/packages/resident/pages/bills/index',
      )
    )
      return;
    this.visible = true;
    void this.load();
  },
  async onPullDownRefresh() {
    try {
      await this.load();
    } finally {
      wx.stopPullDownRefresh();
    }
  },
  onHide() {
    this.visible = false;
    this.epoch++;
    this.setData({ pickerOpen: false, moreLoading: false });
  },
  onUnload() {
    this.visible = false;
    this.epoch++;
    this.off();
  },
  async load() {
    if (!currentCredential()) {
      this.showGuest();
      return;
    }
    const epoch = ++this.epoch;
    this.setData({
      signed: true,
      loading: true,
      error: '',
      moreError: '',
      moreLoading: false,
    });
    try {
      const houses: Binding[] = [];
      for (let page = 1; ; page++) {
        const result = await bindings(page, 'active');
        if (epoch !== this.epoch || !this.visible) return;
        houses.push(
          ...result.items.filter(
            (item) => item.status === 'active' && item.effective_enabled,
          ),
        );
        if (page * result.page_size >= result.total) break;
      }
      const saved = getSelectedBindingId();
      const selectedBinding =
        houses.find((item) => item.house_id === this.requestedHouseId) ||
        houses.find((item) => item.id === saved) ||
        houses[0] ||
        null;
      const selected = selectedBinding ? bindingView(selectedBinding) : null;
      this.requestedHouseId = '';
      setSelectedBindingId(selected?.id || null);
      this.setData({
        houses,
        selected,
        items: [],
        total: 0,
        page: 1,
        hasMore: false,
      });
      if (selected) await this.readBills(epoch, selected, false);
    } catch (error) {
      if (epoch === this.epoch && this.visible)
        this.setData({ error: errorText(error), items: [], total: 0 });
    } finally {
      if (epoch === this.epoch && this.visible)
        this.setData({ loading: false });
    }
  },
  async readBills(epoch: number, selected: Binding, more: boolean) {
    if (!currentCredential()) {
      this.showGuest();
      return;
    }
    const page = more ? this.data.page + 1 : 1;
    const result = await bills(selected.id, page, this.data.scope);
    if (epoch !== this.epoch || !this.visible) return;
    const rows: BillRow[] = result.items.map((item) => {
      const presentation = billPresentation(item);
      return {
        ...item,
        month: item.billing_month.slice(0, 7).replace('-', '年') + '月',
        amount: money(
          presentation.paid ? item.receivable_cents : item.outstanding_cents,
        ),
        receivable: money(item.receivable_cents),
        settled: money(item.settled_cents),
        paid: presentation.paid,
        label: presentation.label,
        tone: presentation.tone,
      };
    });
    this.setData({
      items: more ? [...this.data.items, ...rows] : rows,
      total: result.total,
      page,
      hasMore: page * result.page_size < result.total,
    });
  },
  async more() {
    if (
      this.data.loading ||
      this.data.moreLoading ||
      !this.data.hasMore ||
      !this.data.selected
    )
      return;
    const epoch = this.epoch;
    this.setData({ moreLoading: true, moreError: '' });
    try {
      await this.readBills(epoch, this.data.selected, true);
    } catch (error) {
      if (epoch === this.epoch && this.visible) {
        if (error instanceof ApiError && [403, 404].includes(error.status))
          this.setData({
            items: [],
            total: 0,
            hasMore: false,
            error: errorText(error),
          });
        else this.setData({ moreError: errorText(error) });
      }
    } finally {
      if (epoch === this.epoch && this.visible)
        this.setData({ moreLoading: false });
    }
  },
  filter(event: WechatMiniprogram.TouchEvent) {
    const scope = event.currentTarget.dataset.scope;
    if (scope !== 'all' && scope !== 'outstanding') return;
    if (scope === this.data.scope) return;
    this.setData({ scope });
    void this.load();
  },
  openPicker() {
    if (!this.data.loading && this.data.houses.length)
      this.setData({ pickerOpen: true });
  },
  closePicker() {
    this.setData({ pickerOpen: false });
  },
  async confirmHouse(
    event: WechatMiniprogram.CustomEvent<{ binding?: Binding }>,
  ) {
    const chosen = this.data.houses.find(
      (item) =>
        item.id === event.detail.binding?.id &&
        item.effective_enabled &&
        item.status === 'active',
    );
    this.setData({ pickerOpen: false });
    if (!chosen || chosen.id === this.data.selected?.id) return;
    setSelectedBindingId(chosen.id);
    const epoch = ++this.epoch;
    this.setData({
      selected: bindingView(chosen),
      loading: true,
      items: [],
      total: 0,
      scope: 'outstanding',
      error: '',
      moreError: '',
    });
    try {
      await this.readBills(epoch, chosen, false);
    } catch (error) {
      if (epoch === this.epoch && this.visible)
        this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch && this.visible)
        this.setData({ loading: false });
    }
  },
  open(event: WechatMiniprogram.TouchEvent) {
    go('bill-detail', { id: event.currentTarget.dataset.id });
  },
  login() {
    go('login', { return_to: pageUrl('bills') });
  },
  records() {
    go('payment-orders');
  },
  claim() {
    go('claim');
  },
  emptyAction() {
    if (!this.data.selected) this.claim();
    else if (this.data.scope === 'outstanding') {
      this.setData({ scope: 'all' });
      void this.load();
    }
  },
});
