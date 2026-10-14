import { PageContainer } from '@ant-design/pro-components';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Button, Card, Form, Input, Tabs } from 'antd';
import { useSearchParams } from '@umijs/max';

import { useAdminSession } from '../../../auth/use-admin-session';
import { adminTitles } from '../../../app/admin-routes';
import { PasswordChangeForm } from '../auth/PasswordChangeForm';
import { useAdminApi, useDirtyForm } from '../hooks';
import { applyFormErrors } from '../form-utils';
import { OperationError, ReadError } from '../../../components/AdminFeedback';
import type { Profile } from '../../../shared/admin-api';

function ProfileForm({ profile }: { profile: Profile }) {
  const api = useAdminApi(),
    client = useQueryClient();
  const { scope, updateDisplayName } = useAdminSession();
  const [form] = Form.useForm();
  const dirty = useDirtyForm();
  const mutation = useMutation({
    mutationFn: (name: string) => api.updateProfile(name),
    onSuccess: (value) => {
      updateDisplayName(value.display_name);
      client.setQueryData(['profile'], value);
      dirty.reset();
    },
    onError: (error) => applyFormErrors(form, error, ['display_name']),
    retry: false,
  });
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={profile}
      onValuesChange={dirty.changed}
      onFinish={(value: { display_name: string }) =>
        mutation.mutate(value.display_name)
      }
    >
      <OperationError error={mutation.error} />
      <Form.Item label="登录名">
        <Input value={profile.login_name} readOnly />
      </Form.Item>
      <Form.Item label="所属后台">
        <Input value={adminTitles[scope]} readOnly />
      </Form.Item>
      <Form.Item
        name="display_name"
        label="显示名称"
        rules={[{ required: true }, { min: 1, max: 80 }]}
      >
        <Input />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={mutation.isPending}>
        保存资料
      </Button>
    </Form>
  );
}
export default function ProfilePage() {
  const api = useAdminApi(),
    { status } = useAdminSession();
  const [params, setParams] = useSearchParams();
  const query = useQuery({
    queryKey: ['profile'],
    queryFn: api.profile,
    enabled: status === 'authenticated',
  });
  const tab = params.get('tab') === 'password' ? 'password' : 'profile';
  return (
    <PageContainer title="个人中心">
      <Card style={{ maxWidth: 680 }}>
        <Tabs
          activeKey={tab}
          onChange={(tab) => setParams({ tab })}
          destroyOnHidden
          items={[
            {
              key: 'profile',
              label: '基本资料',
              children: query.isError ? (
                <ReadError retry={() => void query.refetch()} />
              ) : query.data ? (
                <ProfileForm profile={query.data} />
              ) : (
                <Card loading />
              ),
            },
            {
              key: 'password',
              label: '修改密码',
              children: <PasswordChangeForm />,
            },
          ]}
        />
      </Card>
    </PageContainer>
  );
}
