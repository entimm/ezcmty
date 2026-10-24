import { useEffect, useState } from 'react';
import { Alert, App, Button, Form, Input, Space, Tabs, Tag } from 'antd';
import {
  ApartmentOutlined,
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
  useEffect(() => {
    document.title = `${forced ? '更新安全密码' : '登录'} · ${auth.scope === 'property' ? '物业工作空间' : '平台管理中心'} · 美好社区`;
  }, [forced, auth.scope]);
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  async function submit(values: Record<string, string>) {
    if (busy) return;
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
      setError(reason);
      form.setFieldValue(forced ? 'current_password' : 'password', '');
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <div className="auth-story">
        <span className="eyebrow">NEIGHBORHOOD, CONNECTED</span>
        <h1>
          让每一天的
          <br />
          社区工作，
          <br />
          <span>清晰而从容。</span>
        </h1>
        <p>
          连接物业服务与居民生活
          <br />
          专注业务，让管理更有序。
        </p>
        <div className="auth-lines">
          <ApartmentOutlined />
        </div>
        <div className="auth-footer">美好社区 · 社区物业服务平台</div>
      </div>
      <div className="auth-form">
        <div className="auth-form-inner">
          <Tag color="blue">
            {auth.scope === 'property' ? '物业工作空间' : '平台管理中心'}
          </Tag>
          <h2>{forced ? '设置新的安全密码' : '欢迎回来'}</h2>
          <p className="muted">
            {forced
              ? '首次登录或重置密码后，需要先完成密码更新。'
              : '请输入当前后台的账号与密码，开始今天的工作。'}
          </p>
          {forced && (
            <Alert
              type="info"
              showIcon
              title="请验证当前密码，并设置新的安全密码。"
              style={{ margin: '24px 0' }}
            />
          )}
          {error !== undefined && <ReadError error={error} />}
          <Form
            form={form}
            layout="vertical"
            onFinish={(values) => void submit(values as Record<string, string>)}
            disabled={busy}
            size="large"
            style={{ marginTop: 28 }}
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
              <SafetyCertificateOutlined />{' '}
              {auth.scope === 'property' ? '物业' : '平台'}独立安全会话
            </span>
            {forced && (
              <Button
                type="link"
                disabled={busy}
                onClick={() => void auth.logout().catch(setError)}
              >
                退出登录
              </Button>
            )}
          </div>
        </div>
      </div>
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
