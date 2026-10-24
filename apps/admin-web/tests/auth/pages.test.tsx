import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  auth: {
    scope: 'property',
    login: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn(),
    updateName: vi.fn(),
  },
  admin: {
    scope: 'property',
    session: {
      scope: 'property_admin',
      subjectId: 'person-1',
      loginName: 'staff@example.test',
      displayName: '王晓敏',
    },
    request: vi.fn(),
    setDirty: vi.fn(),
    confirmLeave: vi.fn(),
  },
}));
vi.mock('../../src/auth/session', () => ({ useSession: () => mocks.auth }));
vi.mock('../../src/app/navigation', () => ({ navigate: mocks.navigate }));
vi.mock('../../src/shared/context', () => ({ useAdmin: () => mocks.admin }));
import { AuthPage, ProfilePage } from '../../src/auth/Pages';
import { ApiError } from '../../src/shared/request';

function show(element: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <App>{element}</App>
    </QueryClientProvider>,
  );
}

function fillLoginForm() {
  fireEvent.change(screen.getByRole('textbox', { name: '登录账号' }), {
    target: { value: 'staff@example.test' },
  });
  fireEvent.change(screen.getByLabelText('密码'), {
    target: { value: 'existing-account-value' },
  });
}

function fillPasswordForm() {
  fireEvent.change(screen.getByLabelText('当前密码'), {
    target: { value: 'old-account-value' },
  });
  fireEvent.change(screen.getByLabelText('新密码'), {
    target: { value: 'NewExample123!AB' },
  });
  fireEvent.change(screen.getByLabelText('确认新密码'), {
    target: { value: 'NewExample123!AB' },
  });
}

async function failLogin(reason: Error) {
  mocks.auth.login.mockRejectedValue(reason);
  show(<AuthPage forced={false} returnTo="/" />);
  fillLoginForm();
  fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));
  return screen.findByRole('alert');
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.auth.scope = 'property';
  mocks.auth.login.mockResolvedValue(undefined);
  mocks.auth.changePassword.mockResolvedValue(undefined);
  mocks.auth.logout.mockResolvedValue(undefined);
  mocks.admin.confirmLeave.mockImplementation((action: () => void) => action());
  mocks.admin.request.mockImplementation(
    async (_path: string, options?: RequestInit) => ({
      id: 'person-1',
      scope: 'property_admin',
      login_name: 'staff@example.test',
      display_name: options?.method === 'PATCH' ? '王晓敏二号' : '王晓敏',
    }),
  );
});

describe('既有账号登录与强制改密', () => {
  it('允许既有登录名包含 @，请求期间阻止重复提交', async () => {
    let finish!: () => void;
    mocks.auth.login.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    show(<AuthPage forced={false} returnTo="/bills" />);
    fireEvent.change(screen.getByRole('textbox', { name: '登录账号' }), {
      target: { value: ' staff@example.test ' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'existing-account-value' },
    });
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));
    await waitFor(() =>
      expect(mocks.auth.login).toHaveBeenCalledWith(
        'staff@example.test',
        'existing-account-value',
      ),
    );
    expect(screen.getByRole('textbox', { name: '登录账号' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));
    expect(mocks.auth.login).toHaveBeenCalledOnce();
    await act(async () => finish());
  });
  it('登录失败保留账号并清空密码', async () => {
    mocks.auth.login.mockRejectedValue(new Error('账号或密码不正确'));
    show(<AuthPage forced={false} returnTo="/" />);
    fireEvent.change(screen.getByRole('textbox', { name: '登录账号' }), {
      target: { value: 'staff@example.test' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'incorrect-value' },
    });
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));
    await screen.findByText('账号或密码不正确');
    expect(screen.getByText('登录失败')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '登录账号' })).toHaveValue(
      'staff@example.test',
    );
    expect(screen.getByLabelText('密码')).toHaveValue('');
  });
  it('强制改密校验确认密码，成功后回到本端登录并保留回跳路径', async () => {
    show(<AuthPage forced returnTo="/bills" />);
    fireEvent.change(screen.getByLabelText('当前密码'), {
      target: { value: 'old-account-value' },
    });
    fireEvent.change(screen.getByLabelText('新密码'), {
      target: { value: 'NewExample123!AB' },
    });
    fireEvent.change(screen.getByLabelText('确认新密码'), {
      target: { value: 'OtherExample123!AB' },
    });
    fireEvent.click(screen.getByRole('button', { name: '更新密码并重新登录' }));
    await screen.findByText('两次密码不一致');
    expect(mocks.auth.changePassword).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('确认新密码'), {
      target: { value: 'NewExample123!AB' },
    });
    fireEvent.click(screen.getByRole('button', { name: '更新密码并重新登录' }));
    await waitFor(() =>
      expect(mocks.auth.changePassword).toHaveBeenCalledWith(
        'old-account-value',
        'NewExample123!AB',
      ),
    );
    expect(mocks.navigate).toHaveBeenCalledWith(
      '/property/login?return_to=%2Fbills',
      true,
    );
  });
});

describe('认证操作错误反馈', () => {
  it.each([
    ['platform', '平台管理中心'],
    ['property', '物业工作空间'],
  ])('%s 登录认证失败显示安全提示并保留账号', async (scope, workspace) => {
    mocks.auth.scope = scope;
    const alert = await failLogin(new ApiError(401));
    expect(
      screen.getByRole('heading', { name: workspace }),
    ).toBeInTheDocument();
    expect(within(alert).getByText('登录失败')).toBeInTheDocument();
    expect(within(alert).getByText('登录名或密码错误')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '登录账号' })).toHaveValue(
      'staff@example.test',
    );
    expect(screen.getByLabelText('密码')).toHaveValue('');
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it.each([
    {
      name: '网络连接中断',
      error: new Error('网络连接中断，写入结果尚未确定，请先核实原记录。', {
        cause: new TypeError('Failed to fetch'),
      }),
      title: '网络连接失败',
      description: '请检查网络连接后重新提交。',
    },
    {
      name: '服务不可用',
      error: new ApiError(503),
      title: '服务暂不可用',
      description: '请稍后重新提交。',
    },
  ])(
    '登录$name时显示可执行的说明且不自动重发',
    async ({ error, title, description }) => {
      const alert = await failLogin(error);
      expect(within(alert).getByText(title)).toBeInTheDocument();
      expect(within(alert).getByText(description)).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: '登录账号' })).toHaveValue(
        'staff@example.test',
      );
      expect(screen.getByLabelText('密码')).toHaveValue('');
      expect(screen.getByRole('button', { name: /登\s*录/ })).toBeEnabled();
      expect(mocks.auth.login).toHaveBeenCalledOnce();
    },
  );

  it('登录限流显示服务端等待秒数，并可展开请求标识', async () => {
    const alert = await failLogin(
      new ApiError(429, undefined, 'request-login-limit', '25'),
    );
    expect(within(alert).getByText('操作过于频繁')).toBeInTheDocument();
    expect(within(alert).getByText('请在 25 秒后重试。')).toBeInTheDocument();
    const summary = within(alert).getByText('请求标识');
    fireEvent.click(summary);
    expect(summary.closest('details')).toHaveAttribute('open');
    expect(within(alert).getByText('request-login-limit')).toBeVisible();
  });

  it.each([
    ['未返回', undefined],
    ['无效值', 'invalid'],
    ['零秒', '0'],
  ])('限流等待时间为%s时不编造等待秒数', async (_name, retryAfter) => {
    const alert = await failLogin(
      new ApiError(429, undefined, undefined, retryAfter),
    );
    expect(within(alert).getByText('操作过于频繁')).toBeInTheDocument();
    expect(within(alert).getByText('请稍后再试。')).toBeInTheDocument();
    expect(within(alert).queryByText(/秒后重试/)).not.toBeInTheDocument();
  });

  it.each([
    {
      name: '网络连接中断',
      error: new Error('写入结果尚未确定', {
        cause: new TypeError('Failed to fetch'),
      }),
      title: '密码更新结果待确认',
    },
    { name: '服务不可用', error: new ApiError(503), title: '服务暂不可用' },
  ])('强制改密$name时引导确认结果且不误报成功', async ({ error, title }) => {
    mocks.auth.changePassword.mockRejectedValue(error);
    show(<AuthPage forced returnTo="/bills" />);
    fillPasswordForm();
    fireEvent.click(screen.getByRole('button', { name: '更新密码并重新登录' }));
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(
      screen.getByText(
        '请先退出登录，再使用新密码登录确认。若密码未更新，请使用原密码登录。',
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('当前密码')).toHaveValue('');
    expect(screen.getByLabelText('新密码')).toHaveValue('NewExample123!AB');
    expect(screen.getByLabelText('确认新密码')).toHaveValue('NewExample123!AB');
    expect(
      screen.queryByText('密码已更新，请使用新密码登录'),
    ).not.toBeInTheDocument();
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(mocks.auth.changePassword).toHaveBeenCalledOnce();
    expect(mocks.auth.logout).not.toHaveBeenCalled();
  });

  it.each([
    {
      name: '网络连接中断',
      error: new Error('写入结果尚未确定', {
        cause: new TypeError('Failed to fetch'),
      }),
      title: '退出登录失败',
      description: '请检查网络连接后重新退出。',
    },
    {
      name: '服务不可用',
      error: new ApiError(503),
      title: '服务暂不可用',
      description: '请稍后重新退出。',
    },
  ])(
    '退出$name时显示退出说明并允许重新退出',
    async ({ error, title, description }) => {
      mocks.auth.logout.mockRejectedValueOnce(error);
      show(<AuthPage forced returnTo="/" />);
      fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
      expect(await screen.findByText(title)).toBeInTheDocument();
      expect(screen.getByText(description)).toBeInTheDocument();
      expect(screen.getByLabelText('当前密码')).toBeEnabled();
      expect(screen.getByRole('button', { name: '退出登录' })).toBeEnabled();
      expect(mocks.auth.logout).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
      await waitFor(() => expect(mocks.auth.logout).toHaveBeenCalledTimes(2));
      expect(screen.queryByText(description)).not.toBeInTheDocument();
    },
  );
});

describe('认证操作互斥', () => {
  it('快速重复退出只发送一次请求，退出在途时阻止改密，完成后解锁', async () => {
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    mocks.auth.logout.mockReturnValue(pending);
    show(<AuthPage forced returnTo="/" />);
    fillPasswordForm();
    const logout = screen.getByRole('button', { name: '退出登录' });
    const currentPassword = screen.getByLabelText('当前密码');
    const form = currentPassword.closest('form')!;
    try {
      act(() => {
        fireEvent.click(logout);
        fireEvent.click(logout);
      });
      expect(mocks.auth.logout).toHaveBeenCalledOnce();
      expect(logout).toBeDisabled();
      expect(currentPassword).toBeDisabled();
      expect(screen.getByLabelText('新密码')).toBeDisabled();
      expect(screen.getByLabelText('确认新密码')).toBeDisabled();
      await act(async () => {
        fireEvent.submit(form);
      });
      expect(mocks.auth.changePassword).not.toHaveBeenCalled();
    } finally {
      await act(async () => finish());
    }
    expect(logout).toBeEnabled();
    expect(currentPassword).toBeEnabled();
    fireEvent.click(logout);
    await waitFor(() => expect(mocks.auth.logout).toHaveBeenCalledTimes(2));
  });

  it('改密在途时阻止退出和重复改密', async () => {
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    mocks.auth.changePassword.mockReturnValue(pending);
    show(<AuthPage forced returnTo="/" />);
    fillPasswordForm();
    const form = screen.getByLabelText('当前密码').closest('form')!;
    try {
      fireEvent.click(
        screen.getByRole('button', { name: '更新密码并重新登录' }),
      );
      await waitFor(() =>
        expect(mocks.auth.changePassword).toHaveBeenCalledOnce(),
      );
      const logout = screen.getByRole('button', { name: '退出登录' });
      expect(logout).toBeDisabled();
      fireEvent.click(logout);
      await act(async () => {
        fireEvent.submit(form);
      });
      expect(mocks.auth.logout).not.toHaveBeenCalled();
      expect(mocks.auth.changePassword).toHaveBeenCalledOnce();
    } finally {
      await act(async () => finish());
    }
    expect(screen.getByRole('button', { name: '退出登录' })).toBeEnabled();
  });
});

describe('本人资料与密码', () => {
  it('读取当前资料，保存规范化名称后同步会话显示名', async () => {
    show(<ProfilePage />);
    const name = await screen.findByRole('textbox', { name: '显示名称' });
    await waitFor(() => expect(name).toHaveValue('王晓敏'));
    fireEvent.change(name, { target: { value: ' 王晓敏二号 ' } });
    expect(mocks.admin.setDirty).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole('button', { name: '保存资料' }));
    await waitFor(() =>
      expect(mocks.auth.updateName).toHaveBeenCalledWith('王晓敏二号'),
    );
    expect(mocks.admin.request).toHaveBeenCalledWith(
      '/v1/admin-accounts/me',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ display_name: '王晓敏二号' }),
      }),
    );
    expect(name).toHaveValue('王晓敏二号');
    expect(mocks.admin.setDirty).toHaveBeenLastCalledWith(false);
  });
  it('有未保存资料时切换密码页先经过统一离开保护', async () => {
    let confirm!: () => void;
    mocks.admin.confirmLeave.mockImplementation((action: () => void) => {
      confirm = action;
    });
    show(<ProfilePage />);
    const name = await screen.findByRole('textbox', { name: '显示名称' });
    await waitFor(() => expect(name).toHaveValue('王晓敏'));
    fireEvent.change(name, { target: { value: '尚未保存' } });
    fireEvent.click(screen.getByRole('tab', { name: '修改密码' }));
    expect(mocks.admin.confirmLeave).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText('当前密码')).not.toBeInTheDocument();
    act(() => confirm());
    expect(screen.getByLabelText('当前密码')).toBeInTheDocument();
    expect(mocks.admin.setDirty).toHaveBeenLastCalledWith(false);
  });
  it('修改本人密码校验后调用认证操作，成功清空输入', async () => {
    show(<ProfilePage />);
    await screen.findByRole('textbox', { name: '显示名称' });
    fireEvent.click(screen.getByRole('tab', { name: '修改密码' }));
    fireEvent.change(screen.getByLabelText('当前密码'), {
      target: { value: 'old-account-value' },
    });
    fireEvent.change(screen.getByLabelText('新密码'), {
      target: { value: 'NewExample123!AB' },
    });
    fireEvent.change(screen.getByLabelText('确认新密码'), {
      target: { value: 'NewExample123!AB' },
    });
    fireEvent.click(screen.getByRole('button', { name: '更新密码' }));
    await waitFor(() =>
      expect(mocks.auth.changePassword).toHaveBeenCalledWith(
        'old-account-value',
        'NewExample123!AB',
      ),
    );
    await waitFor(() =>
      expect(screen.getByLabelText('当前密码')).toHaveValue(''),
    );
    expect(screen.getByLabelText('新密码')).toHaveValue('');
    expect(screen.getByLabelText('确认新密码')).toHaveValue('');
    expect(
      mocks.admin.request.mock.calls.filter(
        ([, options]) => options?.method === 'PATCH',
      ),
    ).toHaveLength(0);
  });
});
