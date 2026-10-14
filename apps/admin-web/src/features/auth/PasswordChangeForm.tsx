import { useState } from 'react';
import { Alert, Button, Form, Input } from 'antd';
import { useAdminSession } from '../../auth/use-admin-session';
import { useDirtyForm } from '../../shared/hooks/use-dirty-form';
import { applyFormErrors, passwordFields } from '../../shared/form-utils';
import { OperationError } from '../../components/AdminFeedback';

export function PasswordChangeForm() {
  const { changePassword } = useAdminSession();
  const [form] = Form.useForm();
  const dirty = useDirtyForm();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  return (
    <>
      <Alert
        type="info"
        showIcon
        title="保存后当前会话将失效，请使用新密码重新登录。"
        style={{ marginBottom: 24 }}
      />
      <OperationError error={error} />
      <Form
        form={form}
        layout="vertical"
        onValuesChange={dirty.changed}
        onFinish={async (values: {
          current_password: string;
          new_password: string;
        }) => {
          if (busy) return;
          setBusy(true);
          setError(null);
          try {
            await changePassword(values.current_password, values.new_password);
            dirty.reset();
            form.resetFields();
          } catch (error) {
            setError(error);
            applyFormErrors(form, error, ['current_password', 'new_password']);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Form.Item
          name="current_password"
          label="当前密码"
          rules={[{ required: true }, { max: 128 }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        {passwordFields(form, 'new_password', '新密码')}
        <Button type="primary" htmlType="submit" loading={busy}>
          保存新密码
        </Button>
      </Form>
    </>
  );
}
