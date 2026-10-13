import { ProLayout, type MenuDataItem } from '@ant-design/pro-components';
import { HomeOutlined, UserOutlined } from '@ant-design/icons';
import { Link, Outlet, useLocation } from '@umijs/max';

import type { AdminScope } from '../auth/session-context';
import { useAdminSession } from '../auth/use-admin-session';
import { appName } from '../shared/config';

const settings = {
  platform_admin: { title: '平台管理', path: '/platform' },
  property_admin: { title: '物业管理', path: '/property' },
};

export function AdminLayout({ scope }: { scope: AdminScope }) {
  const location = useLocation();
  const { session, hasPermission } = useAdminSession();
  const { title, path } = settings[scope];

  function filterMenu(items: MenuDataItem[]): MenuDataItem[] {
    return items
      .filter(
        (item) =>
          typeof item.permission !== 'string' || hasPermission(item.permission),
      )
      .map((item) => ({
        ...item,
        children: item.children ? filterMenu(item.children) : undefined,
      }));
  }

  return (
    <ProLayout
      title={title}
      logo={false}
      layout="side"
      navTheme={scope === 'platform_admin' ? 'realDark' : 'light'}
      location={location}
      route={{
        path,
        routes: [{ path, name: '首页', icon: <HomeOutlined /> }],
      }}
      menuDataRender={filterMenu}
      menuItemRender={(item, dom) =>
        item.path ? <Link to={item.path}>{dom}</Link> : dom
      }
      avatarProps={{
        icon: <UserOutlined />,
        title: session?.subjectId || '未登录',
      }}
      actionsRender={() => [
        <Link key="portal" to="/">
          返回入口
        </Link>,
      ]}
      footerRender={() => (
        <div style={{ padding: 16, textAlign: 'center' }}>{appName}</div>
      )}
    >
      <Outlet />
    </ProLayout>
  );
}
