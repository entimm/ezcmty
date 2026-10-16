import { onSessionReset, requireSession } from '../../../../auth/resident';
import { ApiError, errorText } from '../../../../shared/http/client';
import {
  claimPage,
  confirm,
  formatTime,
  toastError,
} from '../../../../shared/wechat/ui';
import { binding, releaseBinding } from '../../api';
import { bindingLabels } from '../../presentation';
import { Binding } from '../../types';
Page({
  data: {
    loading: true,
    error: '',
    busy: false,
    item: null as Binding | null,
    label: '',
    granted: '',
    ended: '',
  },
  id: '',
  off: () => {},
  epoch: 0,
  onLoad(options) {
    this.id = options.id || '';
    this.off = onSessionReset(() => {
      this.epoch++;
      this.setData({ item: null, loading: false, busy: false });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
  },
  onShow() {
    void this.load();
  },
  async load() {
    const epoch = ++this.epoch;
    if (
      !requireSession(
        '/packages/resident/pages/house-detail/index?id=' + this.id,
      )
    )
      return;
    this.setData({ loading: true, error: '' });
    try {
      const item = await binding(this.id);
      if (epoch !== this.epoch) return;
      this.setData({
        item,
        label: bindingLabels[item.status],
        granted: formatTime(item.granted_at),
        ended: formatTime(item.ended_at),
      });
    } catch (error) {
      if (epoch === this.epoch) this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  async release() {
    const item = this.data.item;
    if (
      !item ||
      this.data.busy ||
      !(await confirm(
        '解绑房屋',
        '解绑后将失去此房屋的服务权限。如需再次绑定，需要重新提交物业审核。',
      ))
    )
      return;
    this.setData({ busy: true });
    try {
      await releaseBinding(item);
      await this.load();
    } catch (error) {
      toastError(error);
      if (error instanceof ApiError && error.status === 409) await this.load();
    } finally {
      this.setData({ busy: false });
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
});
