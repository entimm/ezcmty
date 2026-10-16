import {
  listPhones,
  onSessionReset,
  requireSession,
} from '../../../../auth/resident';
import { PhoneBinding } from '../../../../auth/types';
import { ApiError, errorText } from '../../../../shared/http/client';
import { claimPage, maskPhone, newKey } from '../../../../shared/wechat/ui';
import * as api from '../../api';
import { detailUrl } from '../../presentation';
import { ClaimInput, Community, House, SpaceNode } from '../../types';
interface PhoneChoice extends PhoneBinding {
  display_phone: string;
}
Page({
  data: {
    step: 1,
    loading: false,
    busy: false,
    error: '',
    unknown: false,
    community: null as Community | null,
    trail: [] as SpaceNode[],
    communityResults: [] as Community[],
    nodes: [] as SpaceNode[],
    houses: [] as House[],
    communityQuery: '',
    roomQuery: '',
    choicePage: 1,
    communityTotal: 0,
    nodeTotal: 0,
    houseTotal: 0,
    house: null as House | null,
    name: '',
    remark: '',
    phones: [] as PhoneChoice[],
    phoneId: '',
    phoneDisplay: '',
  },
  operation: undefined as { data: ClaimInput; key: string } | undefined,
  initialHouse: '',
  initialCommunity: '',
  off: () => {},
  epoch: 0,
  onLoad(options) {
    this.initialHouse = options.house_id || '';
    this.initialCommunity = options.community_id || '';
    this.off = onSessionReset(() => {
      this.epoch++;
      this.operation = undefined;
      this.setData({
        house: null,
        name: '',
        remark: '',
        phones: [],
        phoneId: '',
        phoneDisplay: '',
        unknown: false,
        step: 1,
        loading: false,
        busy: false,
      });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
    this.operation = undefined;
  },
  onShow() {
    const target =
      claimPage +
      (this.initialHouse && this.initialCommunity
        ? '?house_id=' +
          this.initialHouse +
          '&community_id=' +
          this.initialCommunity
        : '');
    if (!requireSession(target)) return;
    if (this.data.house) {
      if (!this.data.unknown) void this.loadPhones();
    } else void this.initialize();
  },
  async initialize() {
    const epoch = ++this.epoch;
    if (this.initialHouse && this.initialCommunity) {
      this.setData({ loading: true, error: '' });
      try {
        const house = await api.house(this.initialCommunity, this.initialHouse);
        if (epoch !== this.epoch) return;
        this.setData({ house, step: 2 });
        await this.loadPhones();
      } catch (error) {
        if (epoch === this.epoch) this.setData({ error: errorText(error) });
      } finally {
        if (epoch === this.epoch) this.setData({ loading: false });
      }
    } else await this.loadChoices();
  },
  retry() {
    if (this.data.step === 1) void this.initialize();
    else void this.loadPhones();
  },
  async loadPhones() {
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    try {
      const phones: PhoneChoice[] = [];
      let page = 1;
      while (true) {
        const result = await listPhones(page);
        if (epoch !== this.epoch) return;
        phones.push(
          ...result.items
            .filter((p) => p.status === 'active')
            .map((p) => ({ ...p, display_phone: maskPhone(p.phone) })),
        );
        if (page * result.page_size >= result.total) break;
        page++;
      }
      const selected =
        phones.find((p) => p.id === this.data.phoneId) || phones[0];
      this.setData({
        phones,
        phoneId: selected?.id || '',
        phoneDisplay: selected?.display_phone || '',
      });
    } catch (error) {
      if (epoch === this.epoch) this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  async loadChoices(more = false) {
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    const page = more ? this.data.choicePage + 1 : 1;
    try {
      if (!this.data.community) {
        const result = await api.communities(this.data.communityQuery, page);
        if (epoch !== this.epoch) return;
        this.setData({
          communityResults: more
            ? [...this.data.communityResults, ...result.items]
            : result.items,
          communityTotal: result.total,
          choicePage: page,
        });
      } else {
        const trail = this.data.trail;
        const node = trail[trail.length - 1];
        const community = this.data.community;
        const [nodes, houses] = await Promise.all([
          api.nodes(community.id, node?.id, page),
          node && node.node_type !== 'phase'
            ? api.houses(community.id, node.id, this.data.roomQuery, page)
            : Promise.resolve({ items: [] as House[], total: 0 }),
        ]);
        if (epoch !== this.epoch) return;
        this.setData({
          nodes: more ? [...this.data.nodes, ...nodes.items] : nodes.items,
          houses: more ? [...this.data.houses, ...houses.items] : houses.items,
          nodeTotal: nodes.total,
          houseTotal: houses.total,
          choicePage: page,
        });
      }
    } catch (error) {
      if (epoch === this.epoch) this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  more() {
    if (!this.data.loading) void this.loadChoices(true);
  },
  communityInput(event: WechatMiniprogram.Input) {
    this.setData({ communityQuery: event.detail.value });
  },
  roomInput(event: WechatMiniprogram.Input) {
    this.setData({ roomQuery: event.detail.value });
  },
  search() {
    if (!this.data.loading) void this.loadChoices();
  },
  selectCommunity(event: WechatMiniprogram.TouchEvent) {
    const community = this.data.communityResults.find(
      (c) => c.id === event.currentTarget.dataset.id,
    );
    if (community) {
      this.setData({
        community,
        trail: [],
        nodes: [],
        houses: [],
        roomQuery: '',
      });
      void this.loadChoices();
    }
  },
  selectNode(event: WechatMiniprogram.TouchEvent) {
    const node = this.data.nodes.find(
      (n) => n.id === event.currentTarget.dataset.id,
    );
    if (node) {
      this.setData({
        trail: [...this.data.trail, node],
        nodes: [],
        houses: [],
        roomQuery: '',
      });
      void this.loadChoices();
    }
  },
  breadcrumb(event: WechatMiniprogram.TouchEvent) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({
      trail: this.data.trail.slice(0, index + 1),
      nodes: [],
      houses: [],
      roomQuery: '',
    });
    void this.loadChoices();
  },
  changeCommunity() {
    this.setData({ community: null, trail: [], nodes: [], houses: [] });
    void this.loadChoices();
  },
  selectHouse(event: WechatMiniprogram.TouchEvent) {
    const house = this.data.houses.find(
      (h) => h.id === event.currentTarget.dataset.id,
    );
    if (house) {
      this.operation = undefined;
      this.setData({ house, step: 2, error: '' });
      void this.loadPhones();
    }
  },
  nameInput(event: WechatMiniprogram.Input) {
    this.setData({ name: event.detail.value });
    this.operation = undefined;
  },
  remarkInput(event: WechatMiniprogram.Input) {
    this.setData({ remark: event.detail.value });
    this.operation = undefined;
  },
  selectPhone(event: WechatMiniprogram.TouchEvent) {
    if (this.data.unknown) return;
    const phone = this.data.phones.find(
      (p) => p.id === event.currentTarget.dataset.id,
    );
    if (phone) {
      this.setData({ phoneId: phone.id, phoneDisplay: phone.display_phone });
      this.operation = undefined;
    }
  },
  addPhone() {
    wx.navigateTo({ url: '/pages/phones/index' });
  },
  next() {
    if (!this.data.name.trim()) {
      this.setData({ error: '请填写你的姓名，便于物业核实' });
      return;
    }
    if (!this.data.phoneId) {
      this.setData({ error: '请先添加并验证一个手机号' });
      return;
    }
    this.setData({ step: 3, error: '' });
    wx.pageScrollTo({ scrollTop: 0 });
  },
  back() {
    if (this.data.busy || this.data.unknown) return;
    this.setData({ step: this.data.step - 1, error: '' });
    if (this.data.step === 1) {
      this.initialHouse = '';
      this.initialCommunity = '';
      void this.loadChoices();
    }
  },
  async submit() {
    if (this.data.busy || !this.data.house) return;
    const epoch = this.epoch;
    if (!this.operation)
      this.operation = {
        key: newKey(),
        data: {
          house_id: this.data.house.id,
          applicant_name: this.data.name.trim(),
          phone_binding_id: this.data.phoneId,
          applicant_remark: this.data.remark.trim() || null,
        },
      };
    this.setData({ busy: true, error: '' });
    try {
      const result = await api.createClaim(
        this.operation.data,
        this.operation.key,
      );
      if (epoch !== this.epoch) return;
      this.operation = undefined;
      this.setData({
        name: '',
        remark: '',
        phones: [],
        phoneId: '',
        phoneDisplay: '',
        unknown: false,
      });
      wx.redirectTo({ url: detailUrl('claim', result.id) });
    } catch (error) {
      const unknown =
        error instanceof ApiError &&
        (error.status === 0 || error.status >= 500);
      if (!unknown) this.operation = undefined;
      this.setData({
        unknown,
        error: unknown
          ? '提交结果尚未确认，请点击重试，或到“我的申请”查看。'
          : errorText(error),
      });
    } finally {
      this.setData({ busy: false });
    }
  },
  applications() {
    wx.navigateTo({ url: '/packages/resident/pages/claims/index' });
  },
});
