import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import { describe, expect, it } from 'vitest';

import App from './App';
import configuredRoutes from '../../config/routes';
import { rootContainer } from '../app';
import PlatformApp from './platform/PlatformApp';
import PlatformHome from './platform/HomePage';
import PropertyApp from './property/PropertyApp';
import PropertyHome from './property/HomePage';
import NotFoundPage from '../components/NotFoundPage';

const pages = {
  '@/app/App': App,
  '@/app/platform/PlatformApp': PlatformApp,
  '@/app/platform/HomePage': PlatformHome,
  '@/app/property/PropertyApp': PropertyApp,
  '@/app/property/HomePage': PropertyHome,
  '@/components/NotFoundPage': NotFoundPage,
};

interface ConfiguredRoute {
  path: string;
  component: string;
  routes?: ConfiguredRoute[];
}

function routeElements(routes: ConfiguredRoute[]): ReactElement[] {
  return routes.map((route) => {
    const Page = pages[route.component as keyof typeof pages];
    return (
      <Route key={route.path} path={route.path} element={<Page />}>
        {route.routes && routeElements(route.routes)}
      </Route>
    );
  });
}

function renderRoutes(path: string) {
  render(
    rootContainer(
      <MemoryRouter initialEntries={[path]}>
        <Routes>{routeElements(configuredRoutes)}</Routes>
      </MemoryRouter>,
    ),
  );
}

describe('admin shell', () => {
  it('renders both portal entry points', () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText('进入平台管理端')).toBeInTheDocument();
    expect(screen.getByText('进入物业管理端')).toBeInTheDocument();
  });
});

describe('configured admin routes', () => {
  it('navigates from the portal into each independent layout', async () => {
    renderRoutes('/');
    fireEvent.click(screen.getByRole('link', { name: '进入平台管理端' }));
    expect(await screen.findByText('平台管理首页')).toBeInTheDocument();
    expect(screen.queryByText('物业管理首页')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: '返回入口' }));
    fireEvent.click(screen.getByRole('link', { name: '进入物业管理端' }));
    expect(await screen.findByText('物业管理首页')).toBeInTheDocument();
    expect(screen.queryByText('平台管理首页')).not.toBeInTheDocument();
  });

  it.each([
    ['/platform', '平台管理首页'],
    ['/property', '物业管理首页'],
  ])('opens %s directly', async (path, title) => {
    renderRoutes(path);
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByText('未登录')).toBeInTheDocument();
  });

  it.each(['/missing', '/platform/missing/deep', '/property/missing/deep'])(
    'renders 404 for %s',
    async (path) => {
      renderRoutes(path);
      expect(await screen.findByText('页面不存在')).toBeInTheDocument();
      expect(screen.queryByText('平台管理首页')).not.toBeInTheDocument();
      expect(screen.queryByText('物业管理首页')).not.toBeInTheDocument();
    },
  );
});
