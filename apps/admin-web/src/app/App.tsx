import { Card, Space, Typography } from 'antd';
import { Link } from '@umijs/max';

import { appName } from '../shared/config';
export default function App() {
  return (
    <Card style={{ maxWidth: 640, margin: '80px auto' }}>
      <Typography.Title level={2}>{appName}</Typography.Title>
      <Space>
        <Link to="/platform">进入平台管理端</Link>
        <Link to="/property">进入物业管理端</Link>
      </Space>
    </Card>
  );
}
