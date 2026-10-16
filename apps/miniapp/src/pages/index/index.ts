import { residentHome } from '../../shared/wechat/ui';
Page({
  onLoad() {
    wx.redirectTo({ url: residentHome });
  },
});
