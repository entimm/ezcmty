import { PageContainer } from '@ant-design/pro-components';
import { Card, Col, Row, Typography } from 'antd';
import { Link } from '@umijs/max';
import { useAdminSession } from '../../auth/use-admin-session';
import { adminPath, adminRoot, routesForScope } from '../admin-routes';

export default function HomePage() {
  const { session, hasPermission } = useAdminSession();
  return (
    <PageContainer title="平台管理首页">
      <Card style={{ marginBottom: 24 }}>
        <Typography.Title level={4}>
          {session?.displayName}，欢迎回来
        </Typography.Title>
        <Typography.Text type="secondary">
          当前账号：{session?.loginName} · 平台管理
        </Typography.Text>
      </Card>
      <Row gutter={[16, 16]}>
        {routesForScope('platform_admin')
          .filter(
            (item) =>
              item.menu &&
              item.path !== adminRoot('platform_admin') &&
              (!item.permission || hasPermission(item.permission)),
          )
          .map((item) => (
            <Col key={item.path} xs={24} md={8}>
              <Card>
                <Link to={item.path}>{item.title}</Link>
              </Card>
            </Col>
          ))}
      </Row>
      <Card title="个人账户" style={{ marginTop: 24 }}>
        <Link to={adminPath('platform_admin', '/platform/profile')}>
          个人资料
        </Link>
        <Typography.Text> </Typography.Text>
        <Link
          to={adminPath('platform_admin', '/platform/profile?tab=password')}
        >
          修改密码
        </Link>
      </Card>
    </PageContainer>
  );
}
