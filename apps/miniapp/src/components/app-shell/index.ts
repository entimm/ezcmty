import { back, go } from '../../ui/navigation';
Component({
  options: { styleIsolation: 'apply-shared' },
  properties: {
    title: { type: String, value: '美好社区' },
    tab: { type: String, value: '' },
    interceptBack: Boolean,
    refreshing: Boolean,
    refreshable: { type: Boolean, value: false },
  },
  data: {
    statusHeight: 20,
    navHeight: 44,
    capsuleWidth: 90,
    tabs: [
      { key: 'home', label: '首页', icon: 'house' },
      { key: 'bills', label: '缴费', icon: 'receipt-text' },
      { key: 'houses', label: '房屋', icon: 'building-2' },
      { key: 'profile', label: '我的', icon: 'user-round' },
    ],
  },
  lifetimes: {
    attached() {
      const info = wx.getWindowInfo();
      const capsule = wx.getMenuButtonBoundingClientRect();
      this.setData({
        statusHeight: info.statusBarHeight || 20,
        navHeight: Math.max(
          44,
          (capsule.top - (info.statusBarHeight || 20)) * 2 + capsule.height,
        ),
        capsuleWidth: Math.max(90, info.windowWidth - capsule.left + 8),
      });
    },
  },
  methods: {
    back() {
      if (this.data.interceptBack) this.triggerEvent('back');
      else back();
    },
    refresh() {
      this.triggerEvent('refresh');
    },
    switchTab(event: WechatMiniprogram.TouchEvent) {
      const page = String(event.currentTarget.dataset.page || 'home');
      if (page !== this.data.tab) go(page);
    },
  },
});
