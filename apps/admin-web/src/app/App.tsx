import { Card, Space, Typography } from 'antd';
import { Link, Route, Routes } from 'react-router-dom';

import { appName } from '../shared/config';
import { PlatformApp } from './platform/PlatformApp';
import { PropertyApp } from './property/PropertyApp';
import { NotFoundPage } from '../components/NotFoundPage';

function HomePage() {
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

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/platform/*" element={<PlatformApp />} />
      <Route path="/property/*" element={<PropertyApp />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
