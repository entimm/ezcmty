import { PageContainer } from '@ant-design/pro-components';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Button, Card, Form, Input, Tabs } from 'antd';
import { useSearchParams } from '@umijs/max';

import { useAdminSession } from '../../auth/use-admin-session';
import { useAdminApp } from '../../shared/admin-app-context';
import { PasswordChangeForm } from '../auth/PasswordChangeForm';
import { useProfileApi } from './api';
import { useDirtyForm } from '../../shared/hooks/use-dirty-form';
import { applyFormErrors } from '../../shared/form-utils';
import { OperationError, ReadError } from '../../components/AdminFeedback';
import type { Profile } from '../../shared/api/admin';
import type { PropertyCompany } from '../../shared/api/property';

function ProfileForm({
  profile,
  company,
}: {
  profile: Profile;
  company?: PropertyCompany;
}) {
  const api = useProfileApi(),
    client = useQueryClient();
  const { updateDisplayName } = useAdminSession();
  const { title } = useAdminApp();
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
        <Input value={title} readOnly />
      </Form.Item>
      {company && (
        <Form.Item label="所属物业公司">
          <Input value={`${company.name}（${company.code}）`} readOnly />
        </Form.Item>
      )}
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
  const api = useProfileApi(),
    { request, scope, status, hasPermission } = useAdminSession();
  const [params, setParams] = useSearchParams();
  const query = useQuery({
    queryKey: ['profile'],
    queryFn: api.profile,
    enabled: status === 'authenticated',
  });
  const companyQuery = useQuery({
    queryKey: ['property-companies', 'current'],
    queryFn: () => request<PropertyCompany>('/v1/property-companies/current'),
    enabled:
      status === 'authenticated' &&
      scope === 'property_admin' &&
      hasPermission('property.company.read'),
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
                <ProfileForm profile={query.data} company={companyQuery.data} />
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
