import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, StaleSessionError } from '../../../src/shared/http/client';
import { toastError } from '../../../src/shared/wechat/ui';

let modal: WechatMiniprogram.ShowModalOption;

beforeEach(() => {
  vi.stubGlobal('wx', {
    showToast: vi.fn(),
    showModal: vi.fn((options: WechatMiniprogram.ShowModalOption) => {
      modal = options;
    }),
    setClipboardData: vi.fn(),
  });
});

afterEach(() => vi.unstubAllGlobals());

it.each([true, false])(
  'shows full network details and copies only when confirmed: %s',
  (confirmed) => {
    toastError(
      new ApiError(0, 'network', '网络连接失败，请检查网络后重试', '', {
        method: 'DELETE',
        url: 'https://api.example.test/v1/house-bindings/binding',
        errMsg: 'request:fail timeout',
        errno: 600001,
      }),
    );

    expect(wx.showToast).not.toHaveBeenCalled();
    expect(modal.content).toContain('errMsg: request:fail timeout');
    expect(modal.content).toContain('errno: 600001');
    expect(modal.content).toContain(
      'DELETE https://api.example.test/v1/house-bindings/binding',
    );
    expect(modal.confirmText).toBe('复制详情');
    expect(wx.setClipboardData).not.toHaveBeenCalled();
    modal.success?.({
      confirm: confirmed,
      cancel: !confirmed,
      content: '',
      errMsg: 'showModal:ok',
    });
    if (confirmed)
      expect(wx.setClipboardData).toHaveBeenCalledExactlyOnceWith({
        data: modal.content,
      });
    else expect(wx.setClipboardData).not.toHaveBeenCalled();
  },
);

it('shows business errors through the shared short prompt', () => {
  toastError(new ApiError(409, 'conflict', '操作状态已变化，请刷新'));
  expect(wx.showToast).toHaveBeenCalledExactlyOnceWith({
    title: '操作状态已变化，请刷新',
    icon: 'none',
    duration: 2600,
  });
  expect(wx.showModal).not.toHaveBeenCalled();
});

it('keeps stale session errors silent in the shared prompt', () => {
  toastError(new StaleSessionError());
  expect(wx.showToast).not.toHaveBeenCalled();
  expect(wx.showModal).not.toHaveBeenCalled();
});
