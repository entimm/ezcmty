import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { device } from './harness';

beforeEach(() => {
  vi.resetModules();
  device();
});
afterEach(() => {
  vi.doUnmock('../../src/core/account-api');
  vi.doUnmock('../../src/packages/resident/api');
  vi.unstubAllGlobals();
});

it('replays an uncertain claim with the same key and rejects edits until it is resolved', async () => {
  const { ApiError } = await import('../../src/core/request');
  const createClaim = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(503, 'service.unavailable', '稍后重试'))
    .mockResolvedValue({ id: 'claim-a', status: 'pending' });
  vi.doMock('../../src/packages/resident/api', () => ({ createClaim }));
  const { ClaimSubmission } =
    await import('../../src/packages/resident/claims');
  const controller = new ClaimSubmission();
  const data = {
    house_id: 'house-a',
    applicant_name: ' 张小明 ',
    phone_binding_id: 'phone-a',
    applicant_remark: ' 门牌信息 ',
  };
  await expect(controller.submit(data)).rejects.toMatchObject({ status: 503 });
  expect(controller.unknown).toBe(true);
  await expect(
    controller.submit({ ...data, house_id: 'house-b' }),
  ).rejects.toThrow('原申请结果尚未确认');
  await expect(controller.retry()).resolves.toMatchObject({ id: 'claim-a' });
  expect(createClaim.mock.calls[0]).toEqual(createClaim.mock.calls[1]);
  expect(createClaim.mock.calls[0][0]).toMatchObject({
    applicant_name: '张小明',
    applicant_remark: '门牌信息',
  });
  expect(controller.unknown).toBe(false);
  controller.dispose();
});

it('normalizes a mainland phone, retries only its original authorization, and never persists the code', async () => {
  const { ApiError } = await import('../../src/core/request');
  const { wx } = device();
  const bindPhone = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(0, 'network', '网络异常'))
    .mockResolvedValue({ id: 'phone-a', status: 'unbound' });
  vi.doMock('../../src/core/account-api', () => ({ bindPhone }));
  const { PhoneVerification } = await import('../../src/core/phones');
  const controller = new PhoneVerification();
  await expect(
    controller.authorize('sensitive-one-use-code', '+86 13902806028'),
  ).rejects.toThrow('有效的中国大陆手机号');
  await expect(
    controller.authorize('sensitive-one-use-code', '+8613902806028'),
  ).rejects.toMatchObject({ status: 0 });
  await expect(controller.authorize('replacement-code')).rejects.toThrow(
    '恢复原手机号验证结果',
  );
  await expect(controller.retry()).resolves.toMatchObject({
    status: 'unbound',
  });
  expect(bindPhone.mock.calls[0]).toEqual(bindPhone.mock.calls[1]);
  expect(bindPhone.mock.calls[0][2]).toBe('13902806028');
  expect(wx.setStorageSync).not.toHaveBeenCalled();
  controller.dispose();
});

it('discards a late claim write after the resident session changes', async () => {
  let finish!: (value: { id: string }) => void;
  const createClaim = vi.fn().mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.doMock('../../src/packages/resident/api', () => ({ createClaim }));
  const { ClaimSubmission } =
    await import('../../src/packages/resident/claims');
  const { clearSession } = await import('../../src/core/session');
  const controller = new ClaimSubmission();
  const pending = controller.submit({
    house_id: 'house-a',
    applicant_name: '张小明',
    phone_binding_id: 'phone-a',
    applicant_remark: null,
  });
  clearSession();
  finish({ id: 'old-user-result' });
  await expect(pending).rejects.toMatchObject({ name: 'StaleSessionError' });
  expect(controller.unknown).toBe(false);
  await expect(controller.retry()).rejects.toThrow('填写认领资料');
  controller.dispose();
});

it('discards a late phone authorization and its code after the resident session changes', async () => {
  let finish!: (value: { id: string; status: string }) => void;
  const bindPhone = vi.fn().mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.doMock('../../src/core/account-api', () => ({ bindPhone }));
  const { PhoneVerification } = await import('../../src/core/phones');
  const { clearSession } = await import('../../src/core/session');
  const controller = new PhoneVerification();
  const pending = controller.authorize('old-user-one-use-code', '13902806028');
  clearSession();
  finish({ id: 'old-phone', status: 'active' });
  await expect(pending).rejects.toMatchObject({ name: 'StaleSessionError' });
  expect(controller.unknown).toBe(false);
  await expect(controller.retry()).rejects.toThrow('重新进行微信手机号授权');
  expect(bindPhone).toHaveBeenCalledOnce();
  controller.dispose();
});
