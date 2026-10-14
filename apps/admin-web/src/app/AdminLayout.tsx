import { ProLayout, type MenuDataItem } from '@ant-design/pro-components';
import { HomeOutlined, UserOutlined } from '@ant-design/icons';
import { Link, Outlet, useLocation } from '@umijs/max';
import { App, Dropdown } from 'antd';
import type { ReactNode } from 'react';

import type { AdminScope } from '../auth/session-context';
import { useAdminSession } from '../auth/use-admin-session';
import { appName } from '../shared/config';
import {
  adminPath,
  adminRoot,
  adminRoots,
  adminTitles,
  findAdminRoute,
  routesForScope,
} from './admin-routes';

export function AdminLayout({
  scope,
  children,
}: {
  scope: AdminScope;
  children?: ReactNode;
}) {
  const location = useLocation();
  const { session, hasPermission, logout } = useAdminSession();
  const { message } = App.useApp();
  const title = adminTitles[scope],
    path = adminRoot(scope);
  const profilePath = adminPath(scope, `${adminRoots[scope]}/profile`);

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
  const pages = routesForScope(scope).filter(
    (item) => item.menu && (!item.permission || hasPermission(item.permission)),
  );
  const system = pages
    .filter((item) => item.menu === '系统管理')
    .map((item) => ({ path: item.path, name: item.title }));
  const menu: MenuDataItem[] = [
    {
      path,
      name: pages.find((page) => page.path === path)?.title ?? '首页',
      icon: <HomeOutlined />,
    },
    ...(['物业管理'] as const).flatMap((group) => {
      const children = pages
        .filter((item) => item.menu === group)
        .map((item) => ({ path: item.path, name: item.title }));
      return children.length ? [{ name: group, children }] : [];
    }),
    ...(system.length
      ? [
          {
            path: adminPath(scope, `${adminRoots[scope]}/system`),
            name: '系统管理',
            children: system,
          },
        ]
      : []),
  ];
  const activeRoute = findAdminRoute(scope, location.pathname);
  const hiddenPages: MenuDataItem[] = routesForScope(scope)
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
      navTheme={scope === 'platform_admin' ? 'realDark' : 'light'}
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
