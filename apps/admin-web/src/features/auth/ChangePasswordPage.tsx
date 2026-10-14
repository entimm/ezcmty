import { useState } from 'react';
import { Button, Card, Typography } from 'antd';
import { useAdminSession } from '../../auth/use-admin-session';
import { OperationError } from '../../components/AdminFeedback';
import { PasswordChangeForm } from './PasswordChangeForm';

export default function ChangePasswordPage() {
  const { session, logout } = useAdminSession();
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
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
      <Card style={{ width: 460, maxWidth: '100%' }}>
        <Typography.Title level={3}>首次登录 · 修改密码</Typography.Title>
        <Typography.Paragraph>
          当前账号：{session?.loginName}
        </Typography.Paragraph>
        <PasswordChangeForm />
        <OperationError error={error} />
        <Button
          style={{ marginTop: 16 }}
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await logout();
            } catch (error) {
              setError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          退出登录
        </Button>
      </Card>
    </main>
  );
}
