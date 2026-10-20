import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const auth = vi.hoisted(() => ({
  login: vi.fn(),
  currentCredential: vi.fn(),
}));
vi.mock('../src/auth/resident', () => auth);

interface LoginPage {
  data: {
    busy: boolean;
    error: string;
  };
  setData: (values: object) => void;
  onLoad: (options: { return_to?: string }) => void;
  login: () => Promise<void>;
}

let page: LoginPage;
let ApiError: typeof import('../src/shared/http/client').ApiError;

beforeEach(async () => {
  vi.resetModules();
  auth.login.mockReset().mockResolvedValue(undefined);
  auth.currentCredential.mockReset().mockReturnValue(null);
  vi.stubGlobal('wx', { redirectTo: vi.fn() });
  vi.stubGlobal('Page', (definition: LoginPage) => {
    page = definition;
    page.data = structuredClone(definition.data);
    page.setData = (values: object) => Object.assign(page.data, values);
  });
  await import('../src/pages/login/index');
  ({ ApiError } = await import('../src/shared/http/client'));
  page.onLoad({});
});

afterEach(() => vi.unstubAllGlobals());

it.each([undefined, 0, 600001])(
  'shows the network reason and optional errno %s on the login page',
  async (errno) => {
    auth.login.mockRejectedValue(
      new ApiError(0, 'network', '网络连接失败，请检查网络后重试', '', {
        method: 'POST',
        url: 'https://api.example.test/v1/resident-sessions',
        errMsg: 'request:fail url not in domain list',
        errno,
      }),
    );

    await page.login();

    expect(page.data.error).toContain('网络连接失败，请检查网络后重试');
    expect(page.data.error).toContain(
      'errMsg: request:fail url not in domain list',
    );
    expect(page.data.error).toContain(
      'POST https://api.example.test/v1/resident-sessions',
    );
    if (errno === undefined) expect(page.data.error).not.toContain('errno:');
    else expect(page.data.error).toContain('errno: ' + errno);
    expect(page.data.busy).toBe(false);
    expect(wx.redirectTo).not.toHaveBeenCalled();
  },
);

it('clears old diagnostics when the user retries login', async () => {
  auth.login.mockRejectedValueOnce(
    new ApiError(0, 'network', '网络连接失败，请检查网络后重试', '', {
      method: 'POST',
      url: 'https://api.example.test/v1/resident-sessions',
      errMsg: 'request:fail timeout',
    }),
  );
  await page.login();
  expect(page.data.error).toContain('request:fail timeout');

  let finish!: () => void;
  auth.login.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const retry = page.login();
  expect(page.data.busy).toBe(true);
  expect(page.data.error).toBe('');
  finish();
  await retry;
  expect(page.data.busy).toBe(false);
  expect(wx.redirectTo).toHaveBeenCalledOnce();
});

it('shows business errors without inventing network diagnostics', async () => {
  auth.login.mockRejectedValue(
    new ApiError(422, 'wechat.invalid_code', '微信登录凭证已失效'),
  );
  await page.login();
  expect(page.data.error).toBe('微信登录凭证已失效');
});
