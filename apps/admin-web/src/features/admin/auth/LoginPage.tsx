import { useState } from 'react';
import { Button, Card, Form, Input, Typography } from 'antd';
import { useLocation, useNavigate } from '@umijs/max';

import { useAdminSession } from '../../../auth/use-admin-session';
import {
  adminRoots,
  adminTitles,
  safeReturnTarget,
} from '../../../app/admin-routes';
import { applyFormErrors } from '../form-utils';
import { OperationError } from '../../../components/AdminFeedback';

export default function LoginPage() {
  const { scope, login } = useAdminSession();
  const location = useLocation(),
    navigate = useNavigate();
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: '#f5f7fa',
        padding: 24,
      }}
    >
      <Card style={{ width: 400, maxWidth: '100%' }}>
        <Typography.Title level={3}>
          {adminTitles[scope]} · 登录
        </Typography.Title>
        <OperationError error={error} />
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values: {
            login_name: string;
            password: string;
          }) => {
            if (busy) return;
            setBusy(true);
            setError(null);
            try {
              const session = await login(values.login_name, values.password);
              navigate(
                session.mustChangePassword
                  ? `${adminRoots[scope]}/change-password`
                  : safeReturnTarget(
                      scope,
                      new URLSearchParams(location.search).get('return_to'),
                    ),
                { replace: true },
              );
            } catch (error) {
              setError(error);
              applyFormErrors(form, error, ['login_name', 'password']);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item
            name="login_name"
            label="登录名"
            rules={[{ required: true }, { max: 64 }]}
          >
            <Input autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true }, { max: 128 }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy} block>
            登录
          </Button>
        </Form>
      </Card>
    </main>
  );
}
