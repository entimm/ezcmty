import { onSessionReset, requireSession } from '../../../../auth/resident';
import { ApiError, errorText } from '../../../../shared/http/client';
import {
  claimPage,
  confirm,
  formatTime,
  maskPhone,
  toastError,
} from '../../../../shared/wechat/ui';
import { cancelClaim, claim } from '../../api';
import { claimLabels } from '../../presentation';
import { Claim } from '../../types';
Page({
  data: {
    loading: true,
    error: '',
    busy: false,
    item: null as Claim | null,
    label: '',
    phone: '',
    created: '',
    reviewed: '',
    cancelled: '',
  },
  id: '',
  off: () => {},
  epoch: 0,
  writeEpoch: 0,
  onLoad(options) {
    this.id = options.id || '';
    this.off = onSessionReset(() => {
      this.epoch++;
      this.writeEpoch++;
      this.setData({
        item: null,
        phone: '',
        error: '',
        loading: false,
        busy: false,
      });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
    this.writeEpoch++;
  },
  onShow() {
    void this.load();
  },
  async load() {
    const epoch = ++this.epoch;
    if (
      !requireSession(
        '/packages/resident/pages/claim-detail/index?id=' + this.id,
      )
    )
      return;
    this.setData({ loading: true, error: '' });
    try {
      const item = await claim(this.id);
      if (epoch !== this.epoch) return;
      this.setData({
        item,
        label: claimLabels[item.status],
        phone: maskPhone(item.applicant_phone),
        created: formatTime(item.created_at),
        reviewed: formatTime(item.reviewed_at),
        cancelled: formatTime(item.cancelled_at),
      });
    } catch (error) {
      if (epoch === this.epoch) this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  async cancel() {
    const item = this.data.item;
    if (!item || this.data.busy || this.data.loading || this.data.error) return;
    const epoch = ++this.writeEpoch;
    if (
      !(await confirm(
        '撤回认领申请',
        '撤回后，物业将不再处理此申请。你可以重新发起认领。',
      )) ||
      epoch !== this.writeEpoch ||
      this.data.busy
    )
      return;
    this.setData({ busy: true });
    try {
      await cancelClaim(item);
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
  again() {
    const item = this.data.item;
    if (item)
      wx.navigateTo({
        url:
          claimPage +
          '?house_id=' +
          item.house_id +
          '&community_id=' +
          item.community_id,
      });
  },
  houses() {
    wx.navigateTo({ url: '/packages/resident/pages/houses/index' });
  },
});
