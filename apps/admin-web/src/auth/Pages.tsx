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
import {
  existingPasswordRules,
  hasFormChanges,
  NewPasswordInput,
  newPasswordRules,
} from '../shared/forms';
import { useResource } from '../shared/hooks';
import { PageHeader, Panel, ReadError } from '../shared/ui';
import { ApiError } from '../shared/request';
import type { components } from '../../../../openapi/types';

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
function AuthBrand({ mobile = false }: { mobile?: boolean }) {
  return (
    <div className={`auth-brand${mobile ? ' auth-brand-mobile' : ''}`}>
      <span className="brand-symbol" aria-hidden="true">
        <ApartmentOutlined />
      </span>
      <div>
        <strong>美好社区</strong>
        <span>社区物业服务平台</span>
      </div>
    </div>
  );
}

function CommunityIllustration() {
  return (
    <svg
      className="auth-community"
      viewBox="0 0 560 300"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <pattern
          id="auth-windows"
          x="0"
          y="0"
          width="24"
          height="28"
          patternUnits="userSpaceOnUse"
        >
          <path d="M8 8h6v10H8z" fill="currentColor" opacity=".25" />
        </pattern>
      </defs>
      <circle cx="280" cy="156" r="130" stroke="currentColor" opacity=".1" />
      <circle cx="280" cy="156" r="100" stroke="currentColor" opacity=".08" />
      <path
        d="M44 254h472M88 254V138h94v116m24 0V82h124v172m24 0V118h106v136"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        opacity=".65"
      />
      <path
        d="M206 82l62-30 62 30M354 118l53-24 53 24M88 138l47-22 47 22"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        opacity=".65"
      />
      <path
        d="M104 150h62v84h-62zm118-52h92v136h-92zm148 34h74v102h-74z"
        fill="url(#auth-windows)"
      />
      <path
        d="M254 254v-36h28v36m-158 0v-24h22v24m250 0v-24h22v24M58 254v-34m436 34v-44"
        stroke="currentColor"
        strokeWidth="1.5"
        opacity=".65"
      />
      <path
        d="M58 222c-23 0-23-30 0-42 23 12 23 42 0 42zm436-8c-27 0-27-35 0-49 27 14 27 49 0 49z"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="currentColor"
        fillOpacity=".04"
        opacity=".65"
      />
      <path
        d="M84 276c108-12 284-12 392 0M352 58h32m-16-16v32M142 68h20m-10-10v20"
        stroke="currentColor"
        strokeLinecap="round"
        opacity=".25"
      />
      <circle cx="415" cy="58" r="4" fill="currentColor" opacity=".4" />
    </svg>
  );
}

function PasswordFields() {
  return (
    <>
      <Form.Item
        label="当前密码"
        name="current_password"
        rules={existingPasswordRules}
      >
        <Input.Password autoComplete="current-password" />
      </Form.Item>
      <Form.Item
        label="新密码"
        name="new_password"
        rules={newPasswordRules}
        extra="12–128位，建议组合多种字符，不含换行"
      >
        <NewPasswordInput autoComplete="new-password" />
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
        <NewPasswordInput autoComplete="new-password" />
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
        <AuthBrand />
        <div className="auth-story-copy">
          <CommunityIllustration />
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
        <p className="auth-story-footer">物业服务 · 居民生活 · 美好社区</p>
      </div>
      <section className="auth-form" aria-labelledby="auth-title">
        <AuthBrand mobile />
        <div className="auth-form-inner">
          <header className="auth-form-heading">
            {forced && <p className="auth-workspace">{workspace}</p>}
            <h2 id="auth-title">{forced ? '设置新的安全密码' : workspace}</h2>
            <p className="auth-description">
              {forced
                ? '首次登录或重置密码后，需要先完成密码更新。'
                : `请使用${auth.scope === 'property' ? '物业' : '平台'}账号登录`}
            </p>
          </header>
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
                  rules={existingPasswordRules}
                >
                  <Input.Password
                    autoComplete="current-password"
                    placeholder="请输入密码"
                    prefix={<LockOutlined />}
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

type Profile = components['schemas']['AdminProfile'];
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
