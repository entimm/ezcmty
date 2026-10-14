import { useState } from 'react';
import { Link, useParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Descriptions, Space, Spin, Tag } from 'antd';
import { useAdminSession } from '../../../auth/use-admin-session';
import { OperationError, ReadError } from '../../../components/AdminFeedback';
import { usePropertyApi, usePropertyOperation } from './hooks';
import { CompanyActions } from './CompanyActions';
import CompanyDrawer from './CompanyDrawer';
import { CommunityList } from './CommunitiesPage';
import { CompanyAdmins } from './CompanyAdmins';

export default function CompanyDetailPage() {
  const { company_id } = useParams<{ company_id: string }>();
  const api = usePropertyApi();
  const { status, hasPermission } = useAdminSession();
  const [editing, setEditing] = useState(false);
  const operation = usePropertyOperation();
  const query = useQuery({
    queryKey: ['property-companies', 'detail', company_id],
    queryFn: () => api.company(company_id!),
    enabled:
      !!company_id &&
      status === 'authenticated' &&
      hasPermission('property.company.read'),
  });
  const company = query.data;
  return (
    <PageContainer
      title={company?.name ?? '物业公司详情'}
      breadcrumb={{
        items: [
          { title: <Link to="/platform/property/companies">物业公司</Link> },
          { title: '公司详情' },
        ],
      }}
      extra={
        <Space>
          {company && (
            <CompanyActions
              company={company}
              operation={operation}
              onEdit={() => setEditing(true)}
            />
          )}
          <Link to="/platform/property/companies">返回公司列表</Link>
        </Space>
      }
    >
      <OperationError error={operation.error} />
      {query.isPending ? (
        <Spin />
      ) : query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : (
        company && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            {!company.enabled && (
              <Alert
                type="info"
                showIcon
                title="公司当前停用。可以维护资料、建立小区和开通管理员；启用后物业账号才能登录。"
              />
            )}
            <Card title="基本资料">
              <Descriptions
                column={{ xs: 1, sm: 2 }}
                items={[
                  { key: 'code', label: '公司编码', children: company.code },
                  { key: 'name', label: '公司名称', children: company.name },
                  {
                    key: 'contact',
                    label: '联系人',
                    children: company.contact_name ?? '—',
                  },
                  {
                    key: 'phone',
                    label: '联系电话',
                    children: company.contact_phone ?? '—',
                  },
                  {
                    key: 'enabled',
                    label: '状态',
                    children: (
                      <Tag color={company.enabled ? 'green' : undefined}>
                        {company.enabled ? '启用' : '停用'}
                      </Tag>
                    ),
                  },
                  {
                    key: 'created',
                    label: '创建时间',
                    children: new Date(company.created_at).toLocaleString(),
                  },
                  {
                    key: 'updated',
                    label: '更新时间',
                    children: new Date(company.updated_at).toLocaleString(),
                  },
                ]}
              />
            </Card>
            {hasPermission('property.community.read') && (
              <Card title="关联小区">
                <CommunityList key={company.id} company={company} />
              </Card>
            )}
            {hasPermission('property.admin.read') && (
              <Card title="公司管理员">
                <CompanyAdmins key={company.id} company={company} />
              </Card>
            )}
          </Space>
        )
      )}
      {editing && company && (
        <CompanyDrawer id={company.id} done={() => setEditing(false)} />
      )}
    </PageContainer>
  );
}
