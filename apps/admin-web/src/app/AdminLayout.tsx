import { ProLayout, type MenuDataItem } from '@ant-design/pro-components';
import { HomeOutlined, UserOutlined } from '@ant-design/icons';
import { Link, Outlet, useLocation } from '@umijs/max';
import { App, Dropdown } from 'antd';
import type { ReactNode } from 'react';

import { useAdminApp } from '../shared/admin-app-context';
import { useAdminSession } from '../auth/use-admin-session';
import { appName } from '../shared/config';

export function AdminLayout({ children }: { children?: ReactNode }) {
  const location = useLocation();
  const { session, hasPermission, logout } = useAdminSession();
  const {
    title,
    theme,
    homePath: path,
    profilePath,
    routes,
    menuGroups,
    findRoute,
  } = useAdminApp();
  const { message } = App.useApp();

  function filterMenu(items: MenuDataItem[]): MenuDataItem[] {
    return items
      .filter(
        (item) =>
          typeof item.permission !== 'string' || hasPermission(item.permission),
      )
      .map((item) => ({
        ...item,
        children: item.children ? filterMenu(item.children) : undefined,
      }))
      .filter((item) => !item.children || item.children.length > 0);
  }
  const pages = routes.filter(
    (item) => item.menu && (!item.permission || hasPermission(item.permission)),
  );
  const menu: MenuDataItem[] = [
    {
      path,
      name: pages.find((page) => page.path === path)?.title ?? '首页',
      icon: <HomeOutlined />,
    },
    ...menuGroups.flatMap((group) => {
      const children = pages
        .filter((item) => item.menu === group.id)
        .map((item) => ({ path: item.path, name: item.title }));
      return children.length
        ? [{ path: group.path, name: group.title, children }]
        : [];
    }),
  ];
  const activeRoute = findRoute(location.pathname);
  const hiddenPages: MenuDataItem[] = routes
    .filter((item) => !item.menu && item.states.includes('authenticated'))
    .map((item) => ({
      path: item.path === activeRoute?.path ? location.pathname : item.path,
      name: item.title,
      permission: item.permission,
      hideInMenu: true,
    }));

  return (
    <ProLayout
      title={title}
      logo={false}
      layout="side"
      navTheme={theme}
      location={location}
      route={{
        path,
        routes: [...menu, ...hiddenPages],
      }}
      menuDataRender={filterMenu}
      menuProps={{
        selectedKeys: [activeRoute?.menuParent ?? location.pathname],
      }}
      menuItemRender={(item, dom) =>
        item.path && !item.children?.length ? (
          <Link to={item.path}>{dom}</Link>
        ) : (
          dom
        )
      }
      avatarProps={{
        icon: <UserOutlined />,
        title: session?.displayName || '未登录',
        render: (_, dom) =>
          session ? (
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'profile',
                    label: <Link to={profilePath}>个人资料</Link>,
                  },
                  {
                    key: 'password',
                    label: (
                      <Link to={`${profilePath}?tab=password`}>修改密码</Link>
                    ),
                  },
                  {
                    key: 'logout',
                    label: '退出登录',
                    onClick: () => {
                      void logout().catch((error) =>
                        message.error(
                          error instanceof Error
                            ? error.message
                            : '退出失败，请重试',
                        ),
                      );
                    },
                  },
                ],
              }}
            >
              {dom}
            </Dropdown>
          ) : (
            dom
          ),
      }}
      actionsRender={() => [
        <Link key="portal" to="/">
          {path === '/' ? '返回首页' : '返回入口'}
        </Link>,
      ]}
      footerRender={() => (
        <div style={{ padding: 16, textAlign: 'center' }}>{appName}</div>
      )}
    >
      {children ?? <Outlet />}
    </ProLayout>
  );
}
