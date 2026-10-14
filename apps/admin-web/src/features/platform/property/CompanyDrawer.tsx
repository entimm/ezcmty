import { useQuery } from '@tanstack/react-query';
import { Alert, Form, Input } from 'antd';
import { usePlatformSession } from '../hooks';
import type { CompanyCreate } from '../../../shared/api/property';
import { usePropertyOnboardingApi } from './hooks';
import { PropertyFormDrawer } from './PropertyFormDrawer';

export default function CompanyDrawer({
  id,
  done,
}: {
  id?: string;
  done: () => void;
}) {
  const api = usePropertyOnboardingApi();
  const { status, hasPermission } = usePlatformSession();
  const query = useQuery({
    queryKey: ['property-companies', 'detail', id],
    queryFn: () => api.company(id!),
    enabled:
      !!id &&
      status === 'authenticated' &&
      hasPermission('property.company.read'),
  });
  return (
    <PropertyFormDrawer<CompanyCreate>
      title={id ? '编辑物业公司' : '创建物业公司'}
      loading={!!id && query.isPending}
      error={id ? query.error : undefined}
      retry={() => void query.refetch()}
      initialValues={query.data}
      fields={['code', 'name', 'contact_name', 'contact_phone']}
      done={done}
      save={(values) => {
        const editable = {
          name: values.name,
          contact_name: values.contact_name?.trim() || null,
          contact_phone: values.contact_phone?.trim() || null,
        };
        return id
          ? api.updateCompany(id, editable)
          : api.createCompany({ code: values.code, ...editable });
      }}
    >
      {() => (
        <>
          {!id && (
            <Alert
              type="info"
              showIcon
              title="公司创建后为停用状态。开通公司管理员后，可以启用公司。"
              style={{ marginBottom: 16 }}
            />
          )}
          <Form.Item
            name="code"
            label="公司编码"
            rules={[
              { required: true },
              { max: 64 },
              {
                pattern: /^[A-Za-z0-9][A-Za-z0-9_-]*$/,
                message: '使用字母、数字、下划线或连字符',
              },
            ]}
          >
            <Input readOnly={!!id} />
          </Form.Item>
          <Form.Item
            name="name"
            label="公司名称"
            rules={[{ required: true, whitespace: true }, { max: 160 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="contact_name" label="联系人" rules={[{ max: 80 }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="contact_phone"
            label="联系电话"
            rules={[{ max: 32 }]}
          >
            <Input />
          </Form.Item>
        </>
      )}
    </PropertyFormDrawer>
  );
}
