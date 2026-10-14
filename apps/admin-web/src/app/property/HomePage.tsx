import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Link } from '@umijs/max';
import { Button, Card, Col, Descriptions, Row, Space, Typography } from 'antd';

import { useAdminSession } from '../../auth/use-admin-session';
import { ReadError } from '../../components/AdminFeedback';
import { usePropertyApi } from '../../features/admin/property/hooks';
import { adminPath, adminRoot, routesForScope } from '../admin-routes';

export default function HomePage() {
  const { session, status, hasPermission } = useAdminSession();
  const api = usePropertyApi();
  const canReadCompany = hasPermission('property.company.read');
  const company = useQuery({
    queryKey: ['property-companies', 'current'],
    queryFn: api.currentCompany,
    enabled: status === 'authenticated' && canReadCompany,
  });
  return (
    <PageContainer title="物业工作台">
      <Card style={{ marginBottom: 24 }}>
        <Typography.Title level={4}>
          {session?.displayName}，欢迎回来
        </Typography.Title>
        <Typography.Text type="secondary">
          当前账号：{session?.loginName} · 物业管理
        </Typography.Text>
      </Card>
      {canReadCompany && (
        <Card
          title="所属物业公司"
          style={{ marginBottom: 24 }}
          loading={company.isPending}
          extra={
            <Button
              type="link"
              loading={company.isFetching}
              onClick={() => void company.refetch()}
            >
              刷新
            </Button>
          }
        >
          {company.isError ? (
            <ReadError
              error={company.error}
              retry={() => void company.refetch()}
            />
          ) : company.data ? (
            <Descriptions
              column={{ xs: 1, sm: 2 }}
              items={[
                { key: 'name', label: '公司名称', children: company.data.name },
                { key: 'code', label: '公司编码', children: company.data.code },
                {
                  key: 'contact_name',
                  label: '联系人',
                  children: company.data.contact_name ?? '未填写',
                },
                {
                  key: 'contact_phone',
                  label: '联系电话',
                  children: company.data.contact_phone ?? '未填写',
                },
              ]}
            />
          ) : null}
        </Card>
      )}
      <Row gutter={[16, 16]}>
        {routesForScope('property_admin')
          .filter(
            (route) =>
              route.menu &&
              route.path !== adminRoot('property_admin') &&
              (!route.permission || hasPermission(route.permission)),
          )
          .map((route) => (
            <Col key={route.path} xs={24} md={8}>
              <Card>
                <Link to={route.path}>{route.title}</Link>
              </Card>
            </Col>
          ))}
      </Row>
      <Card title="个人账户" style={{ marginTop: 24 }}>
        <Space>
          <Link to={adminPath('property_admin', '/property/profile')}>
            个人资料
          </Link>
          <Link
            to={adminPath('property_admin', '/property/profile?tab=password')}
          >
            修改密码
          </Link>
        </Space>
      </Card>
    </PageContainer>
  );
}
