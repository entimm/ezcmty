import { useQuery } from '@tanstack/react-query';
import { Form, Input } from 'antd';
import { usePlatformSession } from '../hooks';
import type {
  CommunityCreate,
  PropertyCompany,
} from '../../../shared/api/property';
import { usePropertyOnboardingApi } from './hooks';
import { CompanyPicker } from './CompanyPicker';
import { PropertyFormDrawer } from './PropertyFormDrawer';

export default function CommunityDrawer({
  id,
  company,
  done,
}: {
  id?: string;
  company?: PropertyCompany;
  done: () => void;
}) {
  const api = usePropertyOnboardingApi();
  const { status, hasPermission } = usePlatformSession();
  const query = useQuery({
    queryKey: ['communities', 'detail', id],
    queryFn: () => api.community(id!),
    enabled:
      !!id &&
      status === 'authenticated' &&
      hasPermission('property.community.read'),
  });
  return (
    <PropertyFormDrawer<CommunityCreate>
      title={id ? '编辑小区' : '创建小区'}
      loading={!!id && query.isPending}
      error={id ? query.error : undefined}
      retry={() => void query.refetch()}
      initialValues={query.data ?? { property_company_id: company?.id }}
      fields={['code', 'name', 'property_company_id', 'address']}
      done={done}
      save={(values) =>
        id
          ? api.updateCommunity(id, {
              name: values.name,
              address: values.address,
            })
          : api.createCommunity({
              code: values.code,
              name: values.name,
              address: values.address,
              property_company_id: company?.id ?? values.property_company_id,
            })
      }
    >
      {() => (
        <>
          {id || company ? (
            <Form.Item label="所属物业公司">
              <Input
                readOnly
                value={company?.name ?? query.data?.property_company_name}
              />
            </Form.Item>
          ) : (
            <Form.Item
              name="property_company_id"
              label="所属物业公司"
              rules={[
                { required: true },
                {
                  pattern:
                    /^[0-9a-f]{8}-[0-9a-f]{4}-[47][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
                  message: '请选择有效公司',
                },
              ]}
            >
              <CompanyPicker />
            </Form.Item>
          )}
          <Form.Item
            name="code"
            label="小区编码"
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
            label="小区名称"
            rules={[{ required: true, whitespace: true }, { max: 160 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="address"
            label="地址"
            rules={[{ required: true, whitespace: true }, { max: 255 }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
        </>
      )}
    </PropertyFormDrawer>
  );
}
