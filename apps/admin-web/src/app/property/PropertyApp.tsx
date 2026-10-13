import { PageContainer } from '@ant-design/pro-components';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Empty, Layout, Menu, Typography } from 'antd';
import { useState } from 'react';
import { Link, Route, Routes } from 'react-router-dom';

import { SessionProvider } from '../../auth/SessionProvider';
import { NotFoundPage } from '../../components/NotFoundPage';

export function PropertyApp() {
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider scope="property_admin">
        <Layout style={{ minHeight: '100vh' }}>
          <Layout.Sider theme="light">
            <Typography.Title level={4} style={{ margin: 16 }}>
              物业管理
            </Typography.Title>
            <Menu
              selectedKeys={['home']}
              items={[{ key: 'home', label: <Link to="/property">首页</Link> }]}
            />
          </Layout.Sider>
          <Layout.Content style={{ padding: 24 }}>
            <Routes>
              <Route
                index
                element={
                  <PageContainer title="物业管理首页">
                    <Empty description="暂无内容" />
                  </PageContainer>
                }
              />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </Layout.Content>
        </Layout>
      </SessionProvider>
    </QueryClientProvider>
  );
}
