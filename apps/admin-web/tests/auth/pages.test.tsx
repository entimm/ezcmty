import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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
beforeEach(() => {
  vi.clearAllMocks();
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
