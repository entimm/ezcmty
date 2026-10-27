import { requireIdentity } from '../../../../core/identities';
import * as api from '../../api';
import * as account from '../../../../core/account-api';
import { currentCredential, sessionRevision } from '../../../../core/session';
import { errorText } from '../../../../core/request';
import { maskPhone } from '../../../../core/format';
import { ClaimSubmission } from '../../claims';
import type { Binding, Claim, House, PhoneBinding } from '../../types';
import { back, go, pageUrl } from '../../../../ui/navigation';
import { PageScope } from '../../page-state';
import { addressParts, houseClaimConflict, loadAll } from '../../presentation';

Page({
  data: {
    step: 1,
    title: '填写资料',
    loading: false,
    error: '',
    phoneError: '',
    picker: false,
    house: null as House | null,
    community: '',
    room: '',
    name: '',
    remark: '',
    phones: [] as (PhoneBinding & { masked: string })[],
    phoneId: '',
    confirmedPhone: '',
    busy: false,
    unknown: false,
    leaving: false,
  },
  scope: null as unknown as PageScope,
  submission: null as unknown as ClaimSubmission,
  initialHouseId: '',
  initialCommunityId: '',
  initialized: false,
  completedClaimId: '',
  bindings: [] as Binding[],
  pendingClaims: [] as Claim[],
  onLoad(options: Record<string, string>) {
    this.scope = new PageScope();
    this.submission = new ClaimSubmission();
    this.initialHouseId = options.house_id || options.houseId || '';
    this.initialCommunityId = options.community_id || options.communityId || '';
    this.scope.watch((visible) => {
      this.clearDraft();
      this.initialized = false;
      if (visible) requireIdentity('resident', pageUrl('claim'));
    });
  },
  onShow() {
    if (
      !requireIdentity(
        'resident',
        pageUrl(
          'claim',
          this.initialHouseId
            ? {
                house_id: this.initialHouseId,
                community_id: this.initialCommunityId,
              }
            : undefined,
        ),
      )
    ) {
      this.clearDraft();
      return;
    }
    if (!this.scope.enter()) {
      this.clearDraft();
      this.submission.reset();
      this.initialized = false;
    }
    this.setData({
      busy: this.submission.busy,
      unknown: this.submission.unknown,
    });
    if (!this.initialized && !this.initialHouseId) {
      this.initialized = true;
      this.setData({ picker: true });
    }
    if (this.completedClaimId) {
      const id = this.completedClaimId;
      this.clearDraft();
      wx.redirectTo({ url: pageUrl('claim-detail', { id }) });
      return;
    }
    void this.load();
  },
  onHide() {
    this.scope.leave();
    this.setData({ picker: false, leaving: false });
  },
  onUnload() {
    this.scope.dispose();
    this.submission.dispose();
    this.clearDraft();
  },
  clearDraft() {
    this.completedClaimId = '';
    this.bindings = [];
    this.pendingClaims = [];
    this.setData({
      step: 1,
      title: '填写资料',
      house: null,
      community: '',
      room: '',
      name: '',
      remark: '',
      phones: [],
      phoneId: '',
      confirmedPhone: '',
      error: '',
      phoneError: '',
      picker: false,
      unknown: false,
      busy: false,
    });
  },
  async load() {
    const valid = this.scope.next();
    this.setData({ loading: true, phoneError: '' });
    try {
      const [phones, house, bindings, claims] = await Promise.all([
        loadAll((page) => account.listPhones(page)),
        !this.initialized && this.initialHouseId && this.initialCommunityId
          ? api.house(this.initialCommunityId, this.initialHouseId)
          : Promise.resolve(null),
        loadAll((page) => api.bindings(page, 'active')),
        loadAll((page) => api.claims(page, 'pending')),
      ]);
      if (!valid()) return;
      this.bindings = bindings;
      this.pendingClaims = claims;
      const active = phones.filter((phone) => phone.status === 'active');
      const existing = active.find((phone) => phone.id === this.data.phoneId);
      const confirmedPhoneChanged =
        this.data.step === 2 && !this.submission.unknown && !existing;
      this.setData({
        phones: active.map((phone) => ({
          ...phone,
          masked: maskPhone(phone.phone),
        })),
        phoneId: this.submission.unknown
          ? this.data.phoneId
          : existing?.id || (active.length === 1 ? active[0].id : ''),
        loading: false,
      });
      if (confirmedPhoneChanged)
        this.setData({
          step: 1,
          title: '填写资料',
          error: '号码状态已变化，请重新核对认领资料。',
        });
      if (house) this.applyHouse(house);
      if (!this.initialized) {
        this.initialized = true;
        if (!this.data.house) this.setData({ picker: true });
      }
    } catch (error) {
      if (valid())
        this.setData({ loading: false, phoneError: errorText(error) });
    }
  },
  openPicker() {
    if (!this.data.busy && !this.data.unknown) this.setData({ picker: true });
  },
  closePicker() {
    this.setData({ picker: false });
  },
  applyHouse(house: House) {
    const conflict = houseClaimConflict(
      house.id,
      this.bindings,
      this.pendingClaims,
    );
    if (conflict) {
      this.setData({ error: conflict });
      return;
    }
    const address = addressParts(house.display_address);
    this.setData({
      house,
      community: address.community,
      room: address.room,
      error: '',
    });
  },
  selectHouse(event: WechatMiniprogram.CustomEvent<{ house: House }>) {
    if (this.data.unknown || this.data.busy) return;
    this.applyHouse(event.detail.house);
    this.setData({ picker: false, step: 1, title: '填写资料' });
  },
  next() {
    if (this.data.busy || this.data.unknown || this.data.step !== 1) return;
    if (!this.data.house) {
      this.setData({ error: '请选择要认领的房屋。' });
      return;
    }
    if (this.data.loading || this.data.phoneError) {
      this.setData({ error: '请先完成资料加载后再核对。' });
      return;
    }
    const conflict = houseClaimConflict(
      this.data.house.id,
      this.bindings,
      this.pendingClaims,
    );
    if (conflict) {
      this.setData({ error: conflict });
      return;
    }
    const name = this.data.name.trim();
    if (!name || name.length > 80) {
      this.setData({ error: '请填写 1 至 80 字的姓名。' });
      return;
    }
    const phone = this.data.phones.find(
      (item) => item.id === this.data.phoneId && item.status === 'active',
    );
    if (!phone) {
      this.setData({ error: '请选择本次用于认领的已验证号码。' });
      return;
    }
    this.setData({
      step: 2,
      title: '确认提交',
      name,
      remark: this.data.remark.trim(),
      confirmedPhone: phone.masked,
      error: '',
    });
  },
  previous() {
    if (this.data.busy || this.data.unknown) return;
    this.setData({ step: 1, title: '填写资料', error: '' });
  },
  nameInput(event: WechatMiniprogram.CustomEvent<{ value: string }>) {
    if (!this.data.busy && !this.data.unknown)
      this.setData({ name: event.detail.value });
  },
  remarkInput(event: WechatMiniprogram.CustomEvent<{ value: string }>) {
    if (!this.data.busy && !this.data.unknown)
      this.setData({ remark: event.detail.value });
  },
  selectPhone(event: WechatMiniprogram.TouchEvent) {
    if (!this.data.busy && !this.data.unknown)
      this.setData({ phoneId: event.currentTarget.dataset.id });
  },
  addPhone() {
    if (!this.data.busy && !this.data.unknown)
      go('phones', { returnTo: pageUrl('claim') });
  },
  async submit() {
    if (this.data.busy || !this.data.house || this.data.step !== 2) return;
    if (!this.submission.unknown) {
      const conflict = houseClaimConflict(
        this.data.house.id,
        this.bindings,
        this.pendingClaims,
      );
      if (conflict) {
        this.setData({ error: conflict });
        return;
      }
    }
    const owner = currentCredential()?.userId;
    const revision = sessionRevision();
    const sameSession = () =>
      !!owner &&
      currentCredential()?.userId === owner &&
      sessionRevision() === revision;
    this.setData({ busy: true, error: '' });
    try {
      const claim = this.submission.unknown
        ? await this.submission.retry()
        : await this.submission.submit({
            house_id: this.data.house.id,
            applicant_name: this.data.name.trim(),
            phone_binding_id: this.data.phoneId,
            applicant_remark: this.data.remark.trim() || null,
          });
      if (!sameSession()) return;
      if (!this.scope.isCurrent()) {
        this.completedClaimId = claim.id;
        return;
      }
      this.setData({ busy: false, unknown: false });
      this.clearDraft();
      wx.redirectTo({ url: pageUrl('claim-detail', { id: claim.id }) });
    } catch (error) {
      if (sameSession() && this.scope.isCurrent())
        this.setData({
          busy: false,
          unknown: this.submission.unknown,
          error: errorText(error),
        });
    }
  },
  leave() {
    if (this.data.busy) return;
    if (this.data.step === 2 && !this.data.unknown) {
      this.previous();
      return;
    }
    if (
      this.data.house ||
      this.data.name ||
      this.data.remark ||
      this.data.unknown
    )
      this.setData({ leaving: true });
    else back('houses');
  },
  stay() {
    this.setData({ leaving: false });
  },
  confirmLeave() {
    this.submission.reset();
    this.clearDraft();
    this.setData({ leaving: false });
    back('houses');
  },
  claims() {
    go('claims');
  },
});
