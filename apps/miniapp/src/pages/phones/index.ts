import {
  bindPhone,
  listPhones,
  onSessionReset,
  requireSession,
  unbindPhone,
} from '../../auth/resident';
import { PhoneBinding } from '../../auth/types';
import { ApiError, errorText } from '../../shared/http/client';
import {
  confirm,
  formatTime,
  maskPhone,
  newKey,
  toastError,
} from '../../shared/wechat/ui';
interface PhoneRow extends PhoneBinding {
  display_phone: string;
  display_time: string;
}
interface Pending {
  code: string;
  key: string;
  expected?: string;
}
Page({
  data: {
    loading: true,
    busy: false,
    error: '',
    input: '',
    phones: [] as PhoneRow[],
    total: 0,
    page: 1,
    pending: false,
    inputValid: true,
  },
  operation: undefined as Pending | undefined,
  off: () => {},
  epoch: 0,
  writeEpoch: 0,
  onLoad() {
    this.off = onSessionReset(() => {
      this.epoch++;
      this.writeEpoch++;
      this.operation = undefined;
      this.setData({
        phones: [],
        total: 0,
        page: 1,
        input: '',
        inputValid: true,
        error: '',
        pending: false,
        loading: false,
        busy: false,
      });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
    this.writeEpoch++;
    this.operation = undefined;
  },
  onShow() {
    void this.load();
  },
  async load(more = false) {
    const epoch = ++this.epoch;
    if (!requireSession('/pages/phones/index')) {
      this.setData({ loading: false });
      return;
    }
    this.setData({ loading: true, error: '' });
    try {
      const page = more ? this.data.page + 1 : 1;
      const result = await listPhones(page);
      if (epoch !== this.epoch) return;
      const rows = result.items.map((phone) => ({
        ...phone,
        display_phone: maskPhone(phone.phone),
        display_time: formatTime(phone.last_verified_at),
      }));
      this.setData({
        phones: more ? [...this.data.phones, ...rows] : rows,
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
    void this.load(true);
  },
  input(event: WechatMiniprogram.Input) {
    const value = event.detail.value;
    this.setData({
      input: value,
      inputValid:
        !value.trim() ||
        /^(?:(?:\+86|0086))?1[3-9][0-9]{9}$/.test(value.trim()),
    });
  },
  async authorize(
    event: WechatMiniprogram.CustomEvent<{ code?: string; errMsg?: string }>,
  ) {
    if (this.data.busy || this.data.pending) return;
    const code = event.detail.code;
    if (!code) {
      wx.showToast({ title: '你可以稍后再授权', icon: 'none' });
      return;
    }
    const expected = this.data.input.trim();
    if (expected && !/^(?:(?:\+86|0086))?1[3-9][0-9]{9}$/.test(expected)) {
      this.setData({ error: '请填写有效的中国大陆手机号' });
      return;
    }
    this.operation = { code, key: newKey(), expected: expected || undefined };
    await this.verify();
  },
  async verify() {
    if (!this.operation || this.data.busy) return;
    const epoch = ++this.writeEpoch;
    this.setData({ busy: true, error: '' });
    try {
      await bindPhone(
        this.operation.code,
        this.operation.key,
        this.operation.expected,
      );
      if (epoch !== this.writeEpoch) return;
      this.operation = undefined;
      this.setData({ input: '', pending: false });
      wx.showToast({ title: '手机号已验证', icon: 'success' });
      await this.load();
    } catch (error) {
      if (epoch !== this.writeEpoch) return;
      const unknown =
        error instanceof ApiError &&
        (error.status === 0 || error.status >= 500);
      if (!unknown) this.operation = undefined;
      this.setData({
        pending: unknown,
        error: unknown
          ? '验证结果尚未确认，请点击“重试验证”恢复结果。'
          : errorText(error),
      });
    } finally {
      if (epoch === this.writeEpoch) this.setData({ busy: false });
    }
  },
  async unbind(event: WechatMiniprogram.TouchEvent) {
    const phone = this.data.phones.find(
      (item) => item.id === event.currentTarget.dataset.id,
    );
    if (!phone || this.data.busy || this.data.loading || this.data.pending)
      return;
    const epoch = ++this.writeEpoch;
    if (
      !(await confirm(
        '解绑手机号',
        '此号码将不再用于新申请，已有房屋和申请仍然保留。',
      )) ||
      epoch !== this.writeEpoch ||
      this.data.busy
    )
      return;
    this.setData({ busy: true });
    try {
      await unbindPhone(phone);
      if (epoch !== this.writeEpoch) return;
      await this.load();
    } catch (error) {
      if (epoch !== this.writeEpoch) return;
      toastError(error);
      if (
        error instanceof ApiError &&
        (error.status === 409 || error.status === 0 || error.status >= 500)
      )
        await this.load();
    } finally {
      if (epoch === this.writeEpoch) this.setData({ busy: false });
    }
  },
});
