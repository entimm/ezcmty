import { listPhones, unbindPhone } from '../../core/account-api';
import { PhoneBinding } from '../../core/types';
import {
  currentCredential,
  onSessionReset,
  requireSession,
} from '../../core/session';
import { PhoneVerification } from '../../core/phones';
import { formatTime, maskPhone, normalizePhone } from '../../core/format';
import { ApiError, errorText, StaleSessionError } from '../../core/request';
import { back, go, paths } from '../../ui/navigation';

type Row = PhoneBinding & { masked: string; verified: string };
Page({
  data: {
    signed: false,
    loading: false,
    busy: false,
    error: '',
    moreError: '',
    removeError: '',
    phones: [] as Row[],
    history: [] as Row[],
    historyOpen: false,
    hasMore: false,
    page: 0,
    addOpen: false,
    input: '',
    inputError: '',
    verifyError: '',
    pending: false,
    removeOpen: false,
    removePhone: '',
    returning: false,
  },
  rows: [] as PhoneBinding[],
  operation: undefined as PhoneVerification | undefined,
  removing: undefined as PhoneBinding | undefined,
  epoch: 0,
  writeEpoch: 0,
  visible: false,
  inFlight: undefined as Promise<void> | undefined,
  verificationError: '',
  removalError: '',
  clearVerifiedInput: false,
  off: () => {},
  onLoad(options: Record<string, string | undefined>) {
    this.operation = new PhoneVerification();
    this.setData({ returning: !!(options.returnTo || options.return_to) });
    this.off = onSessionReset(() => {
      this.epoch++;
      this.writeEpoch++;
      this.rows = [];
      this.removing = undefined;
      this.inFlight = undefined;
      this.verificationError = '';
      this.removalError = '';
      this.clearVerifiedInput = false;
      this.setData({
        signed: false,
        loading: false,
        busy: false,
        phones: [],
        history: [],
        input: '',
        inputError: '',
        verifyError: '',
        addOpen: false,
        removeOpen: false,
        pending: false,
        hasMore: false,
        error: '',
        moreError: '',
        removeError: '',
      });
    });
  },
  onShow() {
    this.visible = true;
    this.syncOperation();
    void this.load();
  },
  onHide() {
    this.visible = false;
    this.epoch++;
    this.removing = undefined;
    this.setData({ loading: false, addOpen: false, removeOpen: false });
  },
  onUnload() {
    this.visible = false;
    this.epoch++;
    this.writeEpoch++;
    this.off();
    this.operation?.dispose();
    this.rows = [];
    this.removing = undefined;
    this.inFlight = undefined;
    this.verificationError = '';
    this.removalError = '';
  },
  onPullDownRefresh() {
    void this.load().finally(() => wx.stopPullDownRefresh());
  },
  syncOperation() {
    if (!this.visible) return;
    this.setData({
      busy: !!this.inFlight || !!this.operation?.busy,
      pending: !!this.operation?.unknown,
      verifyError: this.verificationError,
      removeError: this.removalError,
      ...(this.clearVerifiedInput ? { input: '', inputError: '' } : {}),
    });
    this.clearVerifiedInput = false;
  },
  async load(more = false) {
    if (!this.visible || (more && this.data.loading)) return;
    if (!requireSession(paths.phones)) {
      this.setData({ signed: false });
      return;
    }
    const epoch = ++this.epoch;
    this.setData({ signed: true, loading: true, error: '', moreError: '' });
    try {
      const page = more ? this.data.page + 1 : 1;
      const result = await listPhones(page);
      if (!this.visible || epoch !== this.epoch) return;
      this.rows = more ? [...this.rows, ...result.items] : result.items;
      const mapped = this.rows.map((item) => ({
        ...item,
        masked: maskPhone(item.phone),
        verified: formatTime(item.last_verified_at),
      }));
      this.setData({
        phones: mapped.filter((item) => item.status === 'active'),
        history: mapped.filter((item) => item.status === 'unbound'),
        page,
        hasMore: this.rows.length < result.total,
      });
    } catch (error) {
      if (
        !this.visible ||
        epoch !== this.epoch ||
        error instanceof StaleSessionError
      )
        return;
      if (error instanceof ApiError && [403, 404].includes(error.status)) {
        this.rows = [];
        this.removing = undefined;
        this.setData({
          phones: [],
          history: [],
          page: 0,
          hasMore: false,
          removeOpen: false,
          error: errorText(error),
        });
      } else
        this.setData(
          more ? { moreError: errorText(error) } : { error: errorText(error) },
        );
    } finally {
      if (this.visible && epoch === this.epoch)
        this.setData({ loading: false, signed: !!currentCredential() });
    }
  },
  retry() {
    void this.load();
  },
  more() {
    void this.load(true);
  },
  signIn() {
    go('login', { return_to: paths.phones });
  },
  openAdd() {
    if (!this.data.busy)
      this.setData({
        addOpen: true,
        verifyError: this.verificationError,
        pending: !!this.operation?.unknown,
      });
  },
  closeAdd() {
    if (!this.data.busy) this.setData({ addOpen: false });
  },
  input(event: WechatMiniprogram.Input) {
    if (this.data.busy || this.operation?.unknown) return;
    const value = event.detail.value;
    this.setData({
      input: value,
      inputError:
        value.trim() && !normalizePhone(value)
          ? '请填写有效的中国大陆手机号'
          : '',
    });
  },
  async authorize(event: WechatMiniprogram.CustomEvent<{ code?: string }>) {
    if (
      !this.visible ||
      this.data.busy ||
      this.operation?.unknown ||
      !this.operation
    )
      return;
    if (this.data.input.trim() && !normalizePhone(this.data.input)) {
      this.setData({ inputError: '请填写有效的中国大陆手机号' });
      return;
    }
    if (!event.detail.code) {
      this.verificationError = '已取消授权，填写的内容已保留，可稍后重试。';
      this.setData({ verifyError: this.verificationError });
      return;
    }
    await this.trackWrite(
      this.verify(this.operation.authorize(event.detail.code, this.data.input)),
    );
  },
  async retryVerification() {
    if (this.visible && !this.data.busy && this.operation?.unknown)
      await this.trackWrite(this.verify(this.operation.retry()));
  },
  trackWrite(task: Promise<void>): Promise<void> {
    this.inFlight = task;
    const epoch = this.writeEpoch;
    void task
      .finally(() => {
        if (this.inFlight !== task || epoch !== this.writeEpoch) return;
        this.inFlight = undefined;
        if (this.visible) {
          this.syncOperation();
          void this.load();
        }
      })
      .catch(() => {});
    return task;
  },
  async verify(result: Promise<PhoneBinding>) {
    const epoch = ++this.writeEpoch;
    this.verificationError = '';
    this.setData({ busy: true, verifyError: '' });
    try {
      const binding = await result;
      if (epoch !== this.writeEpoch) return;
      if (binding.status !== 'active') {
        this.verificationError = '此号码已解绑，请重新取得微信授权。';
        if (this.visible)
          this.setData({ verifyError: this.verificationError, pending: false });
        return;
      }
      this.clearVerifiedInput = true;
      if (this.visible) {
        this.setData({
          input: '',
          inputError: '',
          addOpen: false,
          pending: false,
        });
        this.clearVerifiedInput = false;
        wx.showToast({ title: '手机号已验证', icon: 'success' });
      }
    } catch (error) {
      if (epoch !== this.writeEpoch || error instanceof StaleSessionError)
        return;
      const pending = !!this.operation?.unknown;
      this.verificationError = pending
        ? '验证结果尚未确认，请恢复原验证结果，避免重复提交。'
        : errorText(error);
      if (this.visible)
        this.setData({ pending, verifyError: this.verificationError });
    }
  },
  openRemove(event: WechatMiniprogram.TouchEvent) {
    if (this.data.busy || this.data.pending) return;
    this.removing = this.rows.find(
      (item) =>
        item.id === event.currentTarget.dataset.id && item.status === 'active',
    );
    if (this.removing) {
      this.removalError = '';
      this.setData({
        removeOpen: true,
        removeError: '',
        removePhone: maskPhone(this.removing.phone),
      });
    }
  },
  closeRemove() {
    if (!this.data.busy) {
      this.removing = undefined;
      this.setData({ removeOpen: false });
    }
  },
  async confirmRemove() {
    if (!this.visible || !this.removing || this.data.busy) return;
    const phone = this.removing;
    await this.trackWrite(this.remove(phone));
  },
  async remove(phone: PhoneBinding) {
    const epoch = ++this.writeEpoch;
    this.removalError = '';
    this.setData({ busy: true, removeError: '' });
    try {
      await unbindPhone(phone);
      if (epoch !== this.writeEpoch) return;
      this.removing = undefined;
      if (this.visible) this.setData({ removeOpen: false });
    } catch (error) {
      if (epoch !== this.writeEpoch || error instanceof StaleSessionError)
        return;
      this.removalError = errorText(error);
      if (this.visible)
        this.setData({ removeError: this.removalError, removeOpen: false });
    }
  },
  toggleHistory() {
    this.setData({ historyOpen: !this.data.historyOpen });
  },
  returnClaim() {
    back('claim');
  },
});
