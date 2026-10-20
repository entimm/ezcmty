import { beforeEach, expect, it, vi } from 'vitest';
const auth = vi.hoisted(() => ({
  bindPhone: vi.fn(),
  listPhones: vi.fn(),
  unbindPhone: vi.fn(),
  reset: () => {},
}));
vi.mock('../src/auth/resident', () => ({
  requireSession: () => true,
  onSessionReset: (callback: () => void) => {
    auth.reset = callback;
    return () => {};
  },
  bindPhone: auth.bindPhone,
  listPhones: auth.listPhones,
  unbindPhone: auth.unbindPhone,
}));
interface PhonePage {
  data: { busy: boolean; pending: boolean; error: string; input: string };
  operation?: { code: string; key: string };
  setData: (values: object) => void;
  onLoad: () => void;
  verify: () => Promise<void>;
}
let page: PhonePage;
beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal('wx', { showToast: vi.fn() });
  vi.stubGlobal('Page', (definition: PhonePage) => {
    page = definition;
    page.data = structuredClone(definition.data);
    page.setData = (values: object) => Object.assign(page.data, values);
  });
  await import('../src/pages/phones/index');
  page.onLoad();
  auth.listPhones.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 100,
  });
});

it('preserves a new account phone verification when an old verification rejects late', async () => {
  let rejectOld!: (error: Error) => void;
  let finishNew!: (result: object) => void;
  auth.bindPhone
    .mockImplementationOnce(
      () =>
        new Promise((_, reject) => {
          rejectOld = reject;
        }),
    )
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishNew = resolve;
        }),
    );
  page.operation = { code: 'old-code', key: 'old-key' };
  const old = page.verify();
  auth.reset();
  const verification = { code: 'new-code', key: 'new-key' };
  page.operation = verification;
  page.data.input = '13900139000';
  const current = page.verify();
  const { StaleSessionError } = await import('../src/shared/http/client');
  rejectOld(new StaleSessionError());
  await old;
  expect(page.operation).toBe(verification);
  expect(page.data.busy).toBe(true);
  expect(page.data.input).toBe('13900139000');
  expect(page.data.error).toBe('');
  finishNew({ id: 'new-phone' });
  await current;
  expect(page.data.busy).toBe(false);
  expect(page.operation).toBeUndefined();
  expect(wx.showToast).toHaveBeenCalledOnce();
});

it('shows network diagnostics alongside the recovery instruction for phone verification', async () => {
  const { ApiError } = await import('../src/shared/http/client');
  const operation = { code: 'private-code', key: 'original-key' };
  page.operation = operation;
  auth.bindPhone.mockRejectedValueOnce(
    new ApiError(0, 'network', '网络错误', '', {
      method: 'POST',
      url: 'https://api.example.test/v1/miniapp-users/me/phone-bindings',
      errMsg: 'request:fail timeout',
      errno: 600001,
    }),
  );

  await page.verify();

  expect(page.data.error).toContain(
    '验证结果尚未确认，请点击“重试验证”恢复结果。',
  );
  expect(page.data.error).toContain('errMsg: request:fail timeout');
  expect(page.data.error).toContain('errno: 600001');
  expect(page.data.error).not.toContain('private-code');
  expect(page.data.pending).toBe(true);
  expect(page.operation).toBe(operation);
});
