import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Form, Input, Space, Tabs } from 'antd';
import {
  ApartmentOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useSession } from './session';
import { navigate } from '../app/navigation';
import { routePath } from '../app/routes';
import { useAdmin } from '../shared/context';
import { hasFormChanges, passwordRules } from '../shared/forms';
import { useResource } from '../shared/hooks';
import { PageHeader, Panel, ReadError } from '../shared/ui';
import { ApiError } from '../shared/request';

type AuthOperation = 'login' | 'password' | 'logout';
function AuthError({
  error,
  operation,
}: {
  error: unknown;
  operation: AuthOperation;
}) {
  if (error == null) return null;
  if (error instanceof DOMException && error.name === 'AbortError') return null;
  const forced = operation === 'password';
  let title =
    operation === 'logout'
      ? '退出登录失败'
      : forced
        ? '密码更新失败'
        : '登录失败';
  let description = error instanceof Error ? error.message : '请稍后再试。';
  const unconfirmedPassword =
    '请先退出登录，再使用新密码登录确认。若密码未更新，请使用原密码登录。';
  if (
    error instanceof TypeError ||
    (error instanceof Error && error.cause instanceof TypeError)
  ) {
    title =
      operation === 'logout'
        ? '退出登录失败'
        : forced
          ? '密码更新结果待确认'
          : '网络连接失败';
    description =
      operation === 'logout'
        ? '请检查网络连接后重新退出。'
        : forced
          ? unconfirmedPassword
          : '请检查网络连接后重新提交。';
  } else if (error instanceof ApiError) {
    if (error.status === 401 && operation === 'login') {
      description = '登录名或密码错误';
    } else if (error.status === 429) {
      title = '操作过于频繁';
      const seconds = /^\d+$/.test(error.retryAfter?.trim() || '')
        ? Number(error.retryAfter)
        : 0;
      description =
        Number.isSafeInteger(seconds) && seconds > 0
          ? `请在 ${seconds} 秒后重试。`
          : '请稍后再试。';
    } else if (error.status >= 500) {
      title = '服务暂不可用';
      description =
        operation === 'logout'
          ? '请稍后重新退出。'
          : forced
            ? unconfirmedPassword
            : '请稍后重新提交。';
    }
  }
  return (
    <Alert
      className="auth-error"
      type="error"
      showIcon
      title={title}
      description={
        <>
          {description}
          {error instanceof ApiError && error.requestId && (
            <details>
              <summary>请求标识</summary>
              {error.requestId}
            </details>
          )}
        </>
      }
    />
  );
}

interface PasswordValues {
  current_password: string;
  new_password: string;
  confirm: string;
}
function PasswordFields() {
  return (
    <>
      <Form.Item
        label="当前密码"
        name="current_password"
        rules={[{ required: true, message: '请输入当前密码' }]}
      >
        <Input.Password autoComplete="current-password" maxLength={128} />
      </Form.Item>
      <Form.Item
        label="新密码"
        name="new_password"
        rules={passwordRules}
        extra="12–128位，包含大小写字母、数字与符号"
      >
        <Input.Password autoComplete="new-password" maxLength={128} />
      </Form.Item>
      <Form.Item
        label="确认新密码"
        name="confirm"
        dependencies={['new_password']}
        rules={[
          { required: true, message: '请再次输入新密码' },
          ({ getFieldValue }) => ({
            validator: (_, value) =>
              !value || getFieldValue('new_password') === value
                ? Promise.resolve()
                : Promise.reject(new Error('两次密码不一致')),
          }),
        ]}
      >
        <Input.Password autoComplete="new-password" maxLength={128} />
      </Form.Item>
    </>
  );
}
export function AuthPage({
  forced,
  returnTo,
}: {
  forced: boolean;
  returnTo: string;
}) {
  const auth = useSession(),
    { message } = App.useApp();
  const workspace = auth.scope === 'property' ? '物业工作空间' : '平台管理中心';
  useEffect(() => {
    document.title = `${forced ? '更新安全密码' : '登录'} · ${auth.scope === 'property' ? '物业工作空间' : '平台管理中心'} · 美好社区`;
  }, [forced, auth.scope]);
  const [form] = Form.useForm();
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<{
      reason: unknown;
      operation: AuthOperation;
    }>();
  async function submit(values: Record<string, string>) {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(undefined);
    try {
      if (forced) {
        await auth.changePassword(values.current_password, values.new_password);
        form.resetFields();
        message.success('密码已更新，请使用新密码登录');
        navigate(routePath(auth.scope, 'login', { return_to: returnTo }), true);
      } else {
        await auth.login(values.login_name.trim(), values.password);
        form.resetFields();
      }
    } catch (reason) {
      setError({ reason, operation: forced ? 'password' : 'login' });
      form.setFieldValue(forced ? 'current_password' : 'password', '');
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  async function logout() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(undefined);
    try {
      await auth.logout();
    } catch (reason) {
      setError({ reason, operation: 'logout' });
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <div className="auth-story">
        <div className="auth-brand">
          <span className="brand-symbol" aria-hidden="true">
            <ApartmentOutlined />
          </span>
          <div>
            <strong>美好社区</strong>
            <span>社区物业服务平台</span>
          </div>
        </div>
        <div className="auth-story-copy">
          <h1>
            让社区工作，
            <span>清晰而从容。</span>
          </h1>
          <p>
            连接物业服务与居民生活
            <br />
            专注业务，让管理更有序。
          </p>
        </div>
        <div className="auth-lines" aria-hidden="true">
          <ApartmentOutlined />
        </div>
      </div>
      <section className="auth-form" aria-labelledby="auth-title">
        <div className="auth-form-inner">
          {forced && <p className="auth-workspace">{workspace}</p>}
          <h2 id="auth-title">{forced ? '设置新的安全密码' : workspace}</h2>
          <p className="auth-description">
            {forced
              ? '首次登录或重置密码后，需要先完成密码更新。'
              : `请使用${auth.scope === 'property' ? '物业' : '平台'}账号登录`}
          </p>
          {forced && (
            <Alert
              type="info"
              showIcon
              title="请验证当前密码，并设置新的安全密码。"
              className="auth-notice"
            />
          )}
          {error && (
            <AuthError error={error.reason} operation={error.operation} />
          )}
          <Form
            className="auth-fields"
            form={form}
            layout="vertical"
            onFinish={(values) => void submit(values as Record<string, string>)}
            disabled={busy}
            size="large"
          >
            {forced ? (
              <PasswordFields />
            ) : (
              <>
                <Form.Item
                  label="登录账号"
                  name="login_name"
                  rules={[
                    {
                      required: true,
                      whitespace: true,
                      message: '请输入登录账号',
                    },
                    { max: 64, message: '账号最多64位' },
                  ]}
                >
                  <Input
                    autoComplete="username"
                    placeholder="请输入登录账号"
                    prefix={<UserOutlined />}
                  />
                </Form.Item>
                <Form.Item
                  label="密码"
                  name="password"
                  rules={[{ required: true, message: '请输入密码' }]}
                >
                  <Input.Password
                    autoComplete="current-password"
                    placeholder="请输入密码"
                    prefix={<LockOutlined />}
                    maxLength={128}
                  />
                </Form.Item>
              </>
            )}
            <Button
              htmlType="submit"
              type="primary"
              size="large"
              block
              loading={busy}
            >
              {forced ? '更新密码并重新登录' : '登录'}
            </Button>
          </Form>
          <div className="auth-help">
            <span>
              <SafetyCertificateOutlined /> 请妥善保管账号与密码
            </span>
            {forced && (
              <Button type="link" disabled={busy} onClick={() => void logout()}>
                退出登录
              </Button>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

interface Profile {
  id: string;
  scope: string;
  login_name: string;
  display_name: string;
}
export function ProfilePage() {
  const { request, session, scope, setDirty, confirmLeave } = useAdmin(),
    auth = useSession(),
    { message } = App.useApp();
  const profile = useResource(['profile'], () =>
    request<Profile>('/v1/admin-accounts/me'),
  );
  const [info] = Form.useForm<{ display_name: string }>(),
    [password] = Form.useForm<PasswordValues>();
  const [tab, setTab] = useState('info'),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  const [initial, setInitial] = useState({ display_name: session.displayName });
  useEffect(() => {
    if (profile.data) {
      const next = { display_name: profile.data.display_name };
      setInitial(next);
      info.setFieldsValue(next);
    }
  }, [profile.data, info]);
  useEffect(() => () => setDirty(false), [setDirty]);
  async function save(values: { display_name: string } | PasswordValues) {
    if (busy) return;
    setBusy(true);
    setError(undefined);
    try {
      if ('display_name' in values) {
        const result = await request<Profile>('/v1/admin-accounts/me', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: values.display_name.trim() }),
        });
        setInitial({ display_name: result.display_name });
        info.setFieldsValue({ display_name: result.display_name });
        auth.updateName(result.display_name);
        setDirty(false);
        message.success('个人资料已保存');
      } else {
        setDirty(false);
        await auth.changePassword(values.current_password, values.new_password);
        password.resetFields();
        message.success('密码已更新，请使用新密码登录');
      }
    } catch (reason) {
      setError(reason);
      if (tab === 'password')
        setDirty(hasFormChanges(password.getFieldsValue()));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader title="个人中心" description="管理本人资料与账户安全" />
      <ReadError error={profile.error} retry={() => void profile.refetch()} />
      {error !== undefined && <ReadError error={error} />}
      <Panel>
        <Tabs
          activeKey={tab}
          onChange={(value) => {
            if (busy) return;
            confirmLeave(() => {
              setTab(value);
              info.setFieldsValue(initial);
              password.resetFields();
              setDirty(false);
              setError(undefined);
            });
          }}
          items={[
            {
              key: 'info',
              label: '个人资料',
              children: (
                <div className="narrow-form">
                  <div className="profile-card">
                    <span className="profile-avatar">
                      {session.displayName.slice(0, 1)}
                    </span>
                    <div>
                      <h3>{session.displayName}</h3>
                      <p className="muted">
                        {scope === 'property' ? '物业工作空间' : '平台管理中心'}
                      </p>
                    </div>
                  </div>
                  <Form
                    form={info}
                    layout="vertical"
                    disabled={busy || profile.isPending || !!profile.error}
                    initialValues={initial}
                    onValuesChange={() =>
                      setDirty(hasFormChanges(info.getFieldsValue(), initial))
                    }
                    onFinish={(values) => void save(values)}
                  >
                    <Form.Item label="登录账号">
                      <Input disabled value={session.loginName} />
                    </Form.Item>
                    <Form.Item
                      name="display_name"
                      label="显示名称"
                      rules={[
                        {
                          required: true,
                          whitespace: true,
                          message: '请输入显示名称',
                        },
                        { max: 80, message: '最多80个字符' },
                      ]}
                    >
                      <Input maxLength={80} />
                    </Form.Item>
                    <Form.Item label="所属后台">
                      <Input
                        disabled
                        value={scope === 'property' ? '物业后台' : '平台后台'}
                      />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={busy}>
                      保存资料
                    </Button>
                  </Form>
                </div>
              ),
            },
            {
              key: 'password',
              label: '修改密码',
              children: (
                <div className="narrow-form">
                  <Alert
                    showIcon
                    type="info"
                    title="密码更新后，原会话将失效，需要重新登录。"
                    style={{ marginBottom: 24 }}
                  />
                  <Form
                    form={password}
                    layout="vertical"
                    disabled={busy}
                    onValuesChange={() =>
                      setDirty(hasFormChanges(password.getFieldsValue()))
                    }
                    onFinish={(values) => void save(values)}
                  >
                    <PasswordFields />
                    <Space>
                      <Button type="primary" htmlType="submit" loading={busy}>
                        更新密码
                      </Button>
                      <Button
                        disabled={busy}
                        onClick={() =>
                          confirmLeave(() => {
                            password.resetFields();
                            setDirty(false);
                          })
                        }
                      >
                        清空
                      </Button>
                    </Space>
                  </Form>
                </div>
              ),
            },
          ]}
        />
      </Panel>
    </>
  );
}
