import {
  lazy,
  Suspense,
  useMemo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import {
  App as AntApp,
  Button,
  ConfigProvider,
  Drawer,
  Empty,
  Input,
  Modal,
  Radio,
  Result,
  Select,
  Space,
  Tag,
  Tooltip,
} from 'antd';
import zhCN from 'antd/locale/zh_CN';
import {
  ApartmentOutlined,
  ArrowRightOutlined,
  BankOutlined,
  ControlOutlined,
  DownOutlined,
  LogoutOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { SessionProvider, useSession } from '../auth/session';
import { AuthPage, ProfilePage } from '../auth/Pages';
import { AdminContext } from '../shared/context';
import { useQuery } from '@tanstack/react-query';
import { Loading, NoAccess, NotFound, ReadError } from '../shared/ui';
import type { Community, Company, Page } from '../shared/types';
import {
  matchRoute,
  resolveScope,
  routePath,
  routes,
  safeReturn,
} from './routes';
import { navigate, setNavigationGuard, useAddress } from './navigation';
import { menus, matchesMenuSearch } from './menus';
import { Dashboard } from './Dashboard';
import './styles.css';

const PlatformPages = lazy(() =>
  import('../features/platform/PlatformPages').then((m) => ({
    default: m.PlatformPages,
  })),
);
const PropertyPages = lazy(() =>
  import('../features/property/PropertyPages').then((m) => ({
    default: m.PropertyPages,
  })),
);
const PlatformImports = lazy(() =>
  import('../features/platform/imports').then((m) => ({
    default: m.PlatformImportsPage,
  })),
);
const PropertyImports = lazy(() =>
  import('../features/property/imports').then((m) => ({
    default: m.PropertyImportsPage,
  })),
);
const PlatformPayments = lazy(() =>
  import('../features/platform/payments').then((m) => ({
    default: m.PlatformPaymentsPage,
  })),
);
const PropertyPayments = lazy(() =>
  import('../features/property/payments').then((m) => ({
    default: m.PropertyPaymentsPage,
  })),
);
const colors = { blue: '#2859db', indigo: '#5553bf', slate: '#365b79' };
type Brand = keyof typeof colors;
function stored(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Preferences are optional. */
  }
}

export default function App() {
  const address = useAddress(),
    pathname = address.split('?')[0],
    scope = resolveScope(window.location.hostname, pathname);
  const [brand, setBrand] = useState<Brand>(() => {
    const value = stored('xlife-admin-brand', 'blue');
    return value in colors ? (value as Brand) : 'blue';
  });
  const [compact, setCompact] = useState(
    () => stored('xlife-admin-density', 'standard') === 'compact',
  );
  const color = colors[brand];
  useEffect(() => {
    remember('xlife-admin-brand', brand);
    remember('xlife-admin-density', compact ? 'compact' : 'standard');
  }, [brand, compact]);
  return (
    <ConfigProvider
      locale={zhCN}
      componentSize={compact ? 'small' : 'middle'}
      theme={{
        token: {
          colorPrimary: color,
          colorInfo: color,
          colorSuccess: '#25815c',
          colorText: '#263248',
          colorTextSecondary: '#657187',
          colorBgLayout: '#f4f6fa',
          borderRadius: 6,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
          fontSize: 14,
          controlHeight: 34,
        },
        components: {
          Table: {
            headerBg: '#f7f9fc',
            headerColor: '#667187',
            cellPaddingBlock: compact ? 9 : 13,
            cellPaddingInline: 16,
            borderColor: '#edf0f5',
          },
          Button: { fontWeight: 500 },
          Modal: { borderRadiusLG: 10 },
          Drawer: { borderRadiusLG: 0 },
          Tabs: { horizontalItemGutter: 28 },
        },
      }}
    >
      <AntApp>
        <div
          className={'product ' + (compact ? 'compact' : '')}
          style={{ '--brand': color, '--primary': color } as CSSProperties}
        >
          {scope === 'portal' ? (
            <Portal />
          ) : scope ? (
            <SessionProvider key={scope} scope={scope}>
              <ScopeApp
                address={address}
                brand={brand}
                setBrand={setBrand}
                compact={compact}
                setCompact={setCompact}
              />
            </SessionProvider>
          ) : (
            <div className="standalone-state">
              <NotFound />
            </div>
          )}
        </div>
      </AntApp>
    </ConfigProvider>
  );
}

function Portal() {
  return (
    <div className="local-portal">
      <span className="brand-symbol">
        <ApartmentOutlined />
      </span>
      <h1>美好社区 · 管理后台</h1>
      <p>请选择当前工作空间</p>
      <div className="portal-grid">
        {(['platform', 'property'] as const).map((scope) => (
          <button key={scope} onClick={() => navigate(`/${scope}`)}>
            <BankOutlined />
            <strong>
              {scope === 'platform' ? '平台管理中心' : '物业工作空间'}
            </strong>
            <span>
              {scope === 'platform'
                ? '物业接入、支付资金与系统治理'
                : '收费管理、房屋住户与日常服务'}
            </span>
            <ArrowRightOutlined />
          </button>
        ))}
      </div>
      <small>本地开发入口 · 正式环境通过各后台独立域名进入</small>
    </div>
  );
}

function ScopeApp({
  address,
  ...appearance
}: {
  address: string;
  brand: Brand;
  setBrand: (value: Brand) => void;
  compact: boolean;
  setCompact: (value: boolean) => void;
}) {
  const auth = useSession(),
    query = new URLSearchParams(address.split('?')[1] || ''),
    match = matchRoute(auth.scope, address.split('?')[0]);
  const page = match?.route.page;
  const returnTo = safeReturn(auth.scope, query.get('return_to'));
  useEffect(() => {
    if (!match) return;
    if (auth.status === 'anonymous' && page !== 'login')
      navigate(
        routePath(auth.scope, 'login', {
          return_to: page === 'change-password' ? returnTo : address,
        }),
        true,
      );
    if (auth.status === 'password_change' && page !== 'change-password')
      navigate(
        routePath(auth.scope, 'change-password', {
          return_to: page === 'login' ? returnTo : address,
        }),
        true,
      );
    if (
      auth.status === 'authenticated' &&
      (page === 'login' || page === 'change-password')
    )
      navigate(returnTo, true);
  }, [auth.status, auth.scope, address, page, returnTo, match]);
  if (auth.status === 'loading')
    return (
      <div className="standalone-state">
        <Loading />
      </div>
    );
  if (auth.status === 'error')
    return (
      <div className="standalone-state">
        <Result
          status="error"
          title="暂时无法确认登录状态"
          subTitle={auth.error}
          extra={
            <Button type="primary" onClick={() => void auth.refreshSession()}>
              重新连接
            </Button>
          }
        />
      </div>
    );
  if (!match)
    return (
      <div className="standalone-state">
        <NotFound back={() => navigate(routePath(auth.scope, 'home'))} />
      </div>
    );
  if (auth.status === 'anonymous' || auth.status === 'password_change')
    return (
      <AuthPage
        forced={auth.status === 'password_change'}
        returnTo={returnTo}
      />
    );
  if (!auth.session) return null;
  return (
    <Workspace
      key={`${auth.scope}:${auth.session.subjectId}:${auth.session.csrfToken}:${[...auth.session.permissions].sort().join(',')}`}
      {...appearance}
      address={address}
    />
  );
}

function Workspace({
  address,
  brand,
  setBrand,
  compact,
  setCompact,
}: {
  address: string;
  brand: Brand;
  setBrand: (value: Brand) => void;
  compact: boolean;
  setCompact: (value: boolean) => void;
}) {
  const auth = useSession(),
    session = auth.session!;
  const { modal, message } = AntApp.useApp();
  const match = useMemo(
    () => matchRoute(auth.scope, address.split('?')[0]),
    [auth.scope, address],
  );
  const page = match?.route.page || 'not-found';
  const params = useMemo(() => {
    const values: Record<string, string> = {
      ...Object.fromEntries(new URLSearchParams(address.split('?')[1] || '')),
      ...match?.params,
    };
    if (values.payment_id) values.id = values.payment_id;
    if (values.batch_id) values.id = values.batch_id;
    return values;
  }, [address, match]);
  const can = useCallback(
    (permission: string) => session.permissions.includes(permission),
    [session.permissions],
  );
  const [dirty, setDirtyState] = useState(false),
    dirtyRef = useRef(false);
  const [settings, setSettings] = useState(false),
    [command, setCommand] = useState(false),
    [search, setSearch] = useState(''),
    [userOpen, setUserOpen] = useState(false);
  const setDirty = useCallback((value: boolean) => {
    dirtyRef.current = value;
    setDirtyState(value);
  }, []);
  const confirmLeave = useCallback(
    (action: () => void) => {
      if (!dirtyRef.current) {
        action();
        return;
      }
      modal.confirm({
        title: '离开前放弃未保存的内容？',
        content: '当前表单尚未提交，切换后需要重新填写。',
        okText: '放弃并继续',
        cancelText: '继续编辑',
        onOk: () => {
          setDirty(false);
          action();
        },
      });
    },
    [modal, setDirty],
  );
  useEffect(() => {
    setNavigationGuard(confirmLeave, () => dirtyRef.current);
    const before = (event: BeforeUnloadEvent) => {
      if (dirtyRef.current) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', before);
    return () => {
      setNavigationGuard();
      window.removeEventListener('beforeunload', before);
    };
  }, [confirmLeave]);
  const communityKey = `xlife-admin:${auth.scope}:${session.subjectId}:community`;
  const [selected, setSelected] = useState(() => stored(communityKey, ''));
  const communities = useQuery({
    queryKey: [auth.scope, session.subjectId, 'context-communities'],
    queryFn: async () => {
      const all: Community[] = [];
      let pageNo = 1,
        total: number;
      do {
        const data = await auth.request<Page<Community>>(
          `/v1/communities?page=${pageNo}&page_size=100`,
        );
        all.push(...data.items);
        total = data.total;
        if (!data.items.length && all.length < total)
          throw new Error('小区列表尚未完整读取，请重试');
        pageNo++;
      } while (all.length < total);
      return all;
    },
    enabled: auth.scope === 'property' && can('property.community.read'),
  });
  const company = useQuery({
    queryKey: [auth.scope, session.subjectId, 'context-company'],
    queryFn: () => auth.request<Company>('/v1/property-companies/current'),
    enabled: auth.scope === 'property' && can('property.company.read'),
  });
  const options = useMemo(() => communities.data || [], [communities.data]);
  const routeCommunity = params.community_id;
  const communityId =
    auth.scope === 'property' ? routeCommunity || selected : '';
  const community = options.find((item) => item.id === communityId);
  const listMemory = useRef<Record<string, Record<string, string>>>({});
  if (
    match &&
    !match.route.parent &&
    !['home', 'profile', 'company'].includes(page)
  ) {
    listMemory.current[`${communityId}:${page}`] = { ...params };
  }
  useEffect(() => {
    if (auth.scope !== 'property' || !communities.data) return;
    if (routeCommunity) {
      if (
        options.some((item) => item.id === routeCommunity) &&
        selected !== routeCommunity
      ) {
        setSelected(routeCommunity);
        remember(communityKey, routeCommunity);
      }
      return;
    }
    if (!options.some((item) => item.id === selected)) {
      const next =
        options.find((item) => item.enabled)?.id || options[0]?.id || '';
      setSelected(next);
      remember(communityKey, next);
    }
  }, [
    auth.scope,
    communities.data,
    options,
    routeCommunity,
    selected,
    communityKey,
  ]);
  const go = useCallback(
    (next: string, values: Record<string, string | undefined> = {}) => {
      setCommand(false);
      setUserOpen(false);
      confirmLeave(() => {
        let routeValues = { ...values };
        const destination = routes[auth.scope].find(
          (item) => item.page === next,
        );
        if (!Object.keys(values).length && match?.route.parent === next) {
          routeValues = params._back
            ? Object.fromEntries(new URLSearchParams(params._back))
            : listMemory.current[`${communityId}:${next}`] || {};
        }
        if (destination?.parent === page && !routeValues._back) {
          const prior = { ...params };
          delete prior.action;
          delete prior._back;
          routeValues._back = new URLSearchParams(prior).toString();
        }
        if (
          auth.scope === 'property' &&
          communityId &&
          !routeValues.community_id &&
          !routes.property.find((item) => item.page === next)?.companyScope
        )
          routeValues.community_id = communityId;
        navigate(routePath(auth.scope, next, routeValues));
        setCommand(false);
        setSearch('');
        setUserOpen(false);
        document.querySelector('.workspace-scroll')?.scrollTo(0, 0);
      });
    },
    [auth.scope, communityId, confirmLeave, match, params, page],
  );
  const groups = menus[auth.scope]
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        const route = routes[auth.scope].find(
          (route) => route.page === item.page,
        );
        return !route?.permission || can(route.permission);
      }),
    }))
    .filter((group) => group.items.length);
  const flat = groups.flatMap((group) => group.items),
    active = match?.route.parent || page;
  const title = match?.route.title || '页面不存在',
    companyScope = auth.scope === 'platform' || match?.route.companyScope;
  const actions =
    auth.scope === 'property'
      ? [
          ...(can('property.bill.create') &&
          can('property.bill.read') &&
          can('property.house.read') &&
          communityId
            ? [
                {
                  label: '新增物业费账单',
                  page: 'bills',
                  params: { action: 'new-bill' },
                },
              ]
            : []),
          ...(can('property.import.create')
            ? [{ label: '新建批量导入', page: 'import-new', params: {} }]
            : []),
        ]
      : [];
  const results = flat.filter((item) => matchesMenuSearch(item, search)),
    quick = actions.filter((item) => item.label.includes(search));
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        if (
          [...document.querySelectorAll('.ant-modal-wrap')].some(
            (item) => item.getClientRects().length,
          )
        )
          return;
        setCommand((value) => !value);
      }
      if (event.key === 'Escape') setCommand(false);
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);
  useEffect(() => {
    document.title = `${title} · ${auth.scope === 'property' ? '物业工作空间' : '平台管理中心'} · 美好社区`;
  }, [title, auth.scope]);
  function switchCommunity(id: string) {
    if (id === communityId) return;
    confirmLeave(() => {
      setSelected(id);
      remember(communityKey, id);
      const list = match?.route.parent || page;
      const target = companyScope ? page : list;
      const clean: Record<string, string | undefined> = companyScope
        ? { ...params }
        : { community_id: id };
      delete clean.community_id;
      if (!companyScope) clean.community_id = id;
      navigate(routePath(auth.scope, target, clean));
      message.success(
        `已切换至${options.find((item) => item.id === id)?.name || '所选小区'}，相关业务数据已同步`,
      );
    });
  }
  const logout = () => {
    setUserOpen(false);
    confirmLeave(() => {
      void auth
        .logout()
        .catch((error) =>
          message.error(
            error instanceof Error ? error.message : '退出失败，请重试',
          ),
        );
    });
  };
  let body: ReactNode;
  if (!match) body = <NotFound back={() => go('home')} />;
  else if (match.route.permission && !can(match.route.permission))
    body = <NoAccess back={() => go('home')} />;
  else if (page === 'home')
    body = <Dashboard companyName={company.data?.name} />;
  else if (page === 'profile') body = <ProfilePage />;
  else if (['imports', 'import-new', 'import-detail'].includes(page)) {
    const Page = auth.scope === 'platform' ? PlatformImports : PropertyImports;
    body = <Page page={page} params={params} go={go} />;
  } else if (
    [
      'payments',
      'payment-detail',
      'reconciliation',
      'payment-configuration',
    ].includes(page)
  ) {
    const Page =
      auth.scope === 'platform' ? PlatformPayments : PropertyPayments;
    body = <Page page={page} params={params} go={go} />;
  } else {
    const Page = auth.scope === 'platform' ? PlatformPages : PropertyPages;
    body = <Page page={page} params={params} go={go} />;
  }
  return (
    <AdminContext.Provider
      value={{
        scope: auth.scope,
        request: auth.request,
        can,
        hasPermission: can,
        session,
        refreshSession: auth.refreshSession,
        communityId,
        community,
        communities: options,
        go,
        page,
        params,
        setDirty,
        confirmLeave,
      }}
    >
      <header className="topbar">
        <a
          className="brand"
          href={routePath(auth.scope, 'home')}
          onClick={(event) => {
            event.preventDefault();
            go('home');
          }}
        >
          <span className="brand-symbol">
            <ApartmentOutlined />
          </span>
          <strong>美好社区</strong>
          <span className="brand-divider" />
          <span className="workspace-name">
            {auth.scope === 'property' ? '物业工作空间' : '平台管理中心'}
          </span>
        </a>
        <div className="header-tools">
          <Tooltip title="搜索菜单与快捷操作 Ctrl / ⌘ K">
            <button className="header-search" onClick={() => setCommand(true)}>
              <SearchOutlined />
              <span>搜索功能或操作</span>
              <kbd>⌘ K</kbd>
            </button>
          </Tooltip>
          <Tooltip title="外观设置">
            <Button
              type="text"
              aria-label="外观设置"
              icon={<ControlOutlined />}
              onClick={() => setSettings(true)}
            />
          </Tooltip>
          <button className="user-trigger" onClick={() => setUserOpen(true)}>
            <span className="avatar">
              {(session.displayName || session.loginName).slice(0, 1)}
            </span>
            <span>{session.displayName || session.loginName}</span>
            <DownOutlined style={{ fontSize: 10 }} />
          </button>
        </div>
      </header>
      <aside className="sidebar">
        <button
          className="org-block org-button"
          disabled={auth.scope === 'platform' || !can('property.company.read')}
          onClick={() => go('company')}
        >
          <div className="org-icon">
            <BankOutlined />
          </div>
          <div>
            <strong>
              {auth.scope === 'property'
                ? company.data?.name || '物业工作空间'
                : '美好社区运营平台'}
            </strong>
            <small>
              {auth.scope === 'property'
                ? '本公司物业管理'
                : '平台运营与资金管理'}
            </small>
          </div>
        </button>
        <nav aria-label="主导航">
          {groups.map((group) => (
            <div className="menu-group" key={group.label}>
              <div className="menu-group-title">{group.label}</div>
              {group.items.map(({ page: id, label, icon: Icon }) => (
                <button
                  key={id}
                  className={'menu-item ' + (active === id ? 'selected' : '')}
                  aria-current={active === id ? 'page' : undefined}
                  onClick={() => go(id)}
                >
                  <Icon />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment-dot" />
          <span>
            {auth.scope === 'property' ? '物业工作空间' : '平台管理中心'}
          </span>
          <SafetyCertificateOutlined />
        </div>
      </aside>
      <div className="main-area">
        <div className="contextbar">
          <div className="context-selector">
            {auth.scope === 'property' ? (
              <>
                <span className="context-icon">
                  <ApartmentOutlined />
                </span>
                <span className="context-label">当前小区</span>
                <Select
                  aria-label="当前小区"
                  variant="borderless"
                  showSearch
                  optionFilterProp="label"
                  value={communityId || undefined}
                  placeholder={
                    communities.isPending ? '正在读取小区' : '请选择小区'
                  }
                  loading={communities.isFetching}
                  onChange={switchCommunity}
                  options={options.map((item) => ({
                    value: item.id,
                    label: item.name + (item.enabled ? '' : '（已停用）'),
                  }))}
                  style={{ minWidth: 148, maxWidth: 260, fontWeight: 600 }}
                  notFoundContent={
                    communities.error
                      ? '读取失败，请在下方重试'
                      : '暂无可选小区'
                  }
                />
                <div className="context-divider" />
                <span
                  className={
                    'scope-explanation ' + (companyScope ? 'company-scope' : '')
                  }
                >
                  {companyScope
                    ? '本页为本公司范围 · 不受小区选择影响'
                    : `本页业务范围：${community?.name || '请选择小区'}`}
                </span>
              </>
            ) : (
              <>
                <BankOutlined />
                <strong>平台管理范围</strong>
                <div className="context-divider" />
                <span className="scope-explanation">
                  按权限管理物业接入、支付资金与系统配置
                </span>
              </>
            )}
          </div>
          <span className="context-right">
            <SafetyCertificateOutlined />{' '}
            {auth.scope === 'property' ? '公司授权范围' : '平台授权范围'}
          </span>
        </div>
        <main className="workspace-scroll">
          <div className="breadcrumb">
            <button onClick={() => go('home')}>工作概览</button>
            {page !== 'home' && (
              <>
                <span>/</span>
                <span>
                  {groups.find((group) =>
                    group.items.some((item) => item.page === active),
                  )?.label || '账户'}
                </span>
                <span>/</span>
                <strong>{title}</strong>
              </>
            )}
            <span className="draft-marker">
              {dirty ? '● 有未保存内容' : ''}
            </span>
          </div>
          {communities.error && (
            <ReadError
              error={communities.error}
              retry={() => void communities.refetch()}
            />
          )}
          <Suspense fallback={<Loading />}>
            <div
              key={`${auth.scope}:${communityScopeKey(companyScope, communityId)}:${page}`}
            >
              {body}
            </div>
          </Suspense>
          <footer className="workspace-footer">
            美好社区 · 让社区服务更有序
          </footer>
        </main>
      </div>
      <Drawer
        title="外观设置"
        open={settings}
        onClose={() => setSettings(false)}
        size={380}
      >
        <h3>主题色</h3>
        <p className="muted">统一应用于导航、主操作与数据强调。</p>
        <Radio.Group
          value={brand}
          onChange={(event) => setBrand(event.target.value as Brand)}
        >
          <Space direction="vertical">
            {Object.entries(colors).map(([key, color]) => (
              <Radio key={key} value={key}>
                <span className="theme-swatch" style={{ background: color }} />
                {
                  (
                    { blue: '专业蓝', indigo: '靛青', slate: '岩蓝' } as Record<
                      string,
                      string
                    >
                  )[key]
                }
              </Radio>
            ))}
          </Space>
        </Radio.Group>
        <h3 style={{ marginTop: 32 }}>信息密度</h3>
        <Radio.Group
          value={compact}
          onChange={(event) => setCompact(event.target.value as boolean)}
          options={[
            { label: '标准 · 舒适阅读', value: false },
            { label: '紧凑 · 高效浏览', value: true },
          ]}
        />
      </Drawer>
      <Modal
        title="我的账户"
        open={userOpen}
        onCancel={() => setUserOpen(false)}
        footer={null}
        width={390}
      >
        <div className="profile-card">
          <div className="profile-avatar">
            {(session.displayName || session.loginName).slice(0, 1)}
          </div>
          <h3>{session.displayName}</h3>
          <p>{session.loginName}</p>
          <Tag>{auth.scope === 'property' ? '物业后台' : '平台后台'}</Tag>
        </div>
        <Button block icon={<UserOutlined />} onClick={() => go('profile')}>
          个人中心
        </Button>
        <Button
          block
          danger
          type="text"
          icon={<LogoutOutlined />}
          onClick={logout}
          style={{ marginTop: 12 }}
        >
          退出登录
        </Button>
      </Modal>
      <Modal
        open={command}
        onCancel={() => {
          setCommand(false);
          setSearch('');
        }}
        footer={null}
        title={null}
        width={620}
        className="command-modal"
        destroyOnHidden
      >
        <div className="command-input">
          <SearchOutlined />
          <Input
            autoFocus
            variant="borderless"
            placeholder="搜索菜单、常用操作…"
            aria-label="搜索菜单、常用操作"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <kbd>ESC</kbd>
        </div>
        <div className="command-context">
          {auth.scope === 'property'
            ? `物业后台 · ${community?.name || '尚未选择小区'}`
            : '平台后台 · 授权管理范围'}
          <Tag>权限内搜索</Tag>
        </div>
        <div className="command-label">菜单与页面</div>
        {results.map(({ page, label, icon: Icon }) => (
          <button
            className="command-result"
            key={page}
            onClick={() => go(page)}
          >
            <Icon />
            <span>{label}</span>
            <ArrowRightOutlined />
          </button>
        ))}
        {quick.length > 0 && (
          <>
            <div className="command-label">常用操作</div>
            {quick.map((action) => (
              <button
                key={action.page}
                className="command-result"
                onClick={() => go(action.page, action.params)}
              >
                <PlusOutlined />
                <span>{action.label}</span>
                <Tag>{community?.name || '本公司'}</Tag>
              </button>
            ))}
          </>
        )}
        {!results.length && !quick.length && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="没有匹配的功能，请尝试业务名称"
          />
        )}
        <div className="command-footer">
          搜索范围遵循当前后台权限；业务跳转保留小区上下文。
        </div>
      </Modal>
    </AdminContext.Provider>
  );
}
function communityScopeKey(companyScope: boolean | undefined, id: string) {
  return companyScope ? 'company' : id;
}
