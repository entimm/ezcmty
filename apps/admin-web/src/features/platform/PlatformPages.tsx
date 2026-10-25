import { useEffect, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  App,
  Avatar,
  Button,
  Dropdown,
  Form,
  Input,
  Modal,
  Result,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  ApartmentOutlined,
  ArrowRightOutlined,
  BankOutlined,
  CheckCircleOutlined,
  EditOutlined,
  EllipsisOutlined,
  PlusOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { useAdmin } from '../../shared/context';
import { ApiError } from '../../shared/request';
import { DetailGrid, PageHeader, Panel, Status } from '../../shared/ui';
import type { Account, Community, Company, Filters } from './api';
import {
  CompanyPicker,
  ListFilter,
  PasswordFields,
  PlatformFormDialog,
  ReadState,
  emptyList,
  errorText,
  pagination,
  Person,
  time,
  usePlatformApi,
  usePlatformWrite,
} from './components';
import { SystemPages } from './SystemPages';

type Go = (page: string, params?: Record<string, string | undefined>) => void;
export interface PlatformPagesProps {
  page: string;
  params: Record<string, string>;
  go: Go;
}
type Edit = {
  kind: 'company' | 'community' | 'company-admin';
  item?: Company | Community | Account;
  company?: Company;
  action?: 'reset';
};
type Detail = {
  kind: 'company' | 'community' | 'company-admin';
  id: string;
  company?: Company;
};
const required = [{ required: true, whitespace: true, message: '请填写此项' }];
const codeRules = [
  { required: true, message: '请输入编码' },
  {
    pattern: /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/,
    message: '使用 1–64 位字母、数字、下划线或短横线',
  },
];
const loginRules = [
  { required: true, message: '请输入登录名' },
  {
    pattern: /^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$/,
    message: '使用 1–64 位字母、数字及 _.@-，首字符为字母或数字',
  },
];
const enabledTag = (enabled: boolean) => (
  <Status>{enabled ? '启用' : '已停用'}</Status>
);
const validPage = (value?: string) =>
  /^[1-9]\d{0,6}$/.test(value || '') ? Number(value) : 1;
function Metric({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: ReactNode;
  detail: string;
  icon: ReactNode;
}) {
  return (
    <div className="metric">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          color: '#69778d',
        }}
      >
        <span>{label}</span>
        {icon}
      </div>
      <strong
        style={{
          fontSize: 28,
          lineHeight: '44px',
          display: 'block',
          color: '#18263c',
        }}
      >
        {value}
      </strong>
      <span className="muted small">{detail}</span>
    </div>
  );
}
function CompanyCommunityCount({ id }: { id: string }) {
  const api = usePlatformApi(),
    { can } = useAdmin();
  const query = useQuery({
    queryKey: ['platform', 'company-community-count', id],
    queryFn: () => api.communities({ property_company_id: id, page_size: 1 }),
    enabled: can('platform.onboarding.read'),
  });
  if (!can('platform.onboarding.read'))
    return <Typography.Text type="secondary">无读取权限</Typography.Text>;
  if (query.isError)
    return (
      <Button type="link" size="small" onClick={() => void query.refetch()}>
        重试
      </Button>
    );
  return (
    <span style={{ fontWeight: 600 }}>
      {query.data?.total ?? '—'}{' '}
      <span className="muted" style={{ fontWeight: 400 }}>
        个
      </span>
    </span>
  );
}

function PlatformDetail({
  detail,
  onClose,
  go,
}: {
  detail: Detail;
  onClose: () => void;
  go: Go;
}) {
  const api = usePlatformApi();
  const query = useQuery<Company | Community | Account>({
    queryKey: [
      'platform',
      'quick-detail',
      detail.kind,
      detail.id,
      detail.company?.id,
    ],
    queryFn: () =>
      detail.kind === 'company'
        ? api.company(detail.id)
        : detail.kind === 'community'
          ? api.community(detail.id)
          : api.companyAdmin(detail.company!.id, detail.id),
  });
  const item = query.data;
  let fields: [string, ReactNode][] = [];
  if (item && detail.kind === 'company') {
    const company = item as Company;
    fields = [
      ['公司名称', company.name],
      ['公司编码', company.code],
      ['联系人', company.contact_name],
      ['联系电话', company.contact_phone],
      ['接入状态', enabledTag(company.enabled)],
      ['创建时间', time(company.created_at)],
    ];
  } else if (item && detail.kind === 'community') {
    const community = item as Community;
    fields = [
      ['小区名称', community.name],
      ['小区编码', community.code],
      ['所属公司', community.property_company_name],
      ['小区状态', enabledTag(community.enabled)],
      ['地址', community.address],
      ['创建时间', time(community.created_at)],
    ];
  } else if (item) {
    const account = item as Account;
    fields = [
      ['显示名称', account.display_name],
      ['登录名', account.login_name],
      ['账号状态', enabledTag(account.enabled)],
      ['首次改密', account.must_change_password ? '需要修改' : '已完成'],
      ['所属公司', detail.company?.name],
      ['创建时间', time(account.created_at)],
    ];
  }
  return (
    <Modal
      open
      title={
        detail.kind === 'company'
          ? '物业公司详情'
          : detail.kind === 'community'
            ? '小区详情'
            : '公司管理员详情'
      }
      width={580}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
    >
      <ReadState
        error={query.error}
        loading={query.isPending}
        retry={() => void query.refetch()}
      >
        {item && (
          <>
            <DetailGrid items={fields} />
            {detail.kind === 'company' && (
              <Button
                type="primary"
                style={{ marginTop: 20 }}
                onClick={() => {
                  onClose();
                  go('company-detail', { company: detail.id });
                }}
              >
                进入完整详情 <ArrowRightOutlined />
              </Button>
            )}
            {detail.kind === 'company-admin' && (
              <Alert
                style={{ marginTop: 20 }}
                type="info"
                showIcon
                title="公司超级管理员 · 本公司全部小区"
                description="授权包含以后新增的小区，不扩展到其他物业公司。"
              />
            )}
          </>
        )}
      </ReadState>
    </Modal>
  );
}

export function PlatformPages(props: PlatformPagesProps) {
  if (['accounts', 'roles', 'audit'].includes(props.page))
    return <SystemPages {...props} />;
  return <PropertyOnboardingPages {...props} />;
}

function PropertyOnboardingPages({ page, params, go }: PlatformPagesProps) {
  const api = usePlatformApi(),
    { can } = useAdmin(),
    { message, modal } = App.useApp();
  const write = usePlatformWrite();
  const [edit, setEdit] = useState<Edit>(),
    [detail, setDetail] = useState<Detail>(),
    [notice, setNotice] = useState<{ text: string; company?: string }>();
  const companyId = params.company || params.id;
  const [companyChoice, setCompanyChoice] = useState<string | undefined>(
    params.property_company_id,
  );
  useEffect(() => {
    setCompanyChoice(params.property_company_id);
  }, [params.property_company_id]);
  useEffect(() => {
    setDetail(undefined);
    setNotice(undefined);
  }, [page]);
  const filterField = params.field === 'code' ? 'code' : 'name';
  const filters: Filters = {
    page: validPage(params.page),
    page_size: 8,
    [filterField]: params.search || undefined,
    enabled:
      params.enabled === 'true'
        ? true
        : params.enabled === 'false'
          ? false
          : undefined,
    property_company_id:
      page === 'platform-communities' ? params.property_company_id : undefined,
  };
  const companies = useQuery({
    queryKey: ['platform', 'companies', filters],
    queryFn: () => api.companies(filters),
    enabled: page === 'companies' && can('platform.onboarding.read'),
  });
  const communities = useQuery({
    queryKey: ['platform', 'communities', filters],
    queryFn: () => api.communities(filters),
    enabled: page === 'platform-communities' && can('platform.onboarding.read'),
  });
  const company = useQuery({
    queryKey: ['platform', 'company', companyId],
    queryFn: () => api.company(companyId),
    enabled:
      page === 'company-detail' &&
      !!companyId &&
      can('platform.onboarding.read'),
  });
  const companyLocator = useQuery({
    queryKey: ['platform', 'company-locator', companyId],
    queryFn: () =>
      api.companyOptions({
        property_company_id: companyId,
        page: 1,
        page_size: 1,
      }),
    enabled:
      page === 'company-detail' &&
      !!companyId &&
      !can('platform.onboarding.read') &&
      (can('platform.system.read') || can('platform.payment_config.read')),
  });
  const stats = useQuery({
    queryKey: ['platform', 'company-stats'],
    queryFn: async () => {
      const [all, active, places] = await Promise.all([
        api.companies({ page_size: 1 }),
        api.companies({ enabled: true, page_size: 1 }),
        can('platform.onboarding.read')
          ? api.communities({ page_size: 1 })
          : Promise.resolve(undefined),
      ]);
      return {
        all: all.total,
        active: active.total,
        communities: places?.total,
      };
    },
    enabled: page === 'companies' && can('platform.onboarding.read'),
  });
  const tab =
    params.tab === 'admins' && can('platform.system.read')
      ? 'admins'
      : can('platform.onboarding.read')
        ? 'communities'
        : 'admins';
  const detailCommunities = useQuery({
    queryKey: [
      'platform',
      'company-communities',
      companyId,
      params.community_page,
    ],
    queryFn: () =>
      api.communities({
        property_company_id: companyId,
        page: validPage(params.community_page),
        page_size: 8,
      }),
    enabled:
      page === 'company-detail' &&
      !!companyId &&
      can('platform.onboarding.read'),
  });
  const admins = useQuery({
    queryKey: ['platform', 'company-admins', companyId, params.admin_page],
    queryFn: () =>
      api.companyAdmins(companyId, {
        page: validPage(params.admin_page),
        page_size: 8,
      }),
    enabled:
      page === 'company-detail' && !!companyId && can('platform.system.read'),
  });
  const update = (values: Record<string, string | undefined>) =>
    go(page, { ...params, ...values });
  const search = (values: Record<string, string | undefined>) =>
    update({
      ...values,
      property_company_id:
        page === 'platform-communities' ? companyChoice : undefined,
      page: undefined,
    });
  const reset = () => {
    setCompanyChoice(undefined);
    go(page);
  };
  const openCompany = (item: Company) =>
    go('company-detail', {
      company: item.id,
      back: new URLSearchParams(params).toString(),
    });
  const back = () =>
    go('companies', Object.fromEntries(new URLSearchParams(params.back || '')));
  const confirm = (
    title: string,
    content: string,
    run: () => Promise<unknown>,
    security = false,
  ) =>
    modal.confirm({
      title,
      content,
      okText: '确认操作',
      cancelText: '取消',
      onOk: async () => {
        try {
          await write.run(run, security);
          message.success('操作已完成');
        } catch (error) {
          message.error(errorText(error));
          throw error;
        }
      },
    });
  const toggleCompany = (item: Company) =>
    confirm(
      `${item.enabled ? '停用' : '启用'}「${item.name}」？`,
      item.enabled
        ? '公司全部物业账号将无法登录，已有会话失效；小区及账号各自的启停状态保留。'
        : '至少须有一名有效公司超级管理员。启用后，物业账号需要重新登录。',
      () => api.updateCompany(item.id, { enabled: !item.enabled }),
    );
  const toggleCommunity = (item: Community) =>
    confirm(
      `${item.enabled ? '停用' : '启用'}「${item.name}」？`,
      item.enabled
        ? '保留历史查询，阻止该小区新增业务。其他小区不受影响。'
        : '恢复小区业务接入资格，所属公司也须处于启用状态。',
      () => api.updateCommunity(item.id, { enabled: !item.enabled }),
    );
  const toggleAdmin = (item: Account) =>
    confirm(
      `${item.enabled ? '停用' : '启用'} ${item.display_name}？`,
      '该账号旧会话将失效。公司必须保留至少一名有效超级管理员。',
      () =>
        api.updateCompanyAdmin(companyId, item.id, { enabled: !item.enabled }),
    );
  const menu = (
    items: {
      key: string;
      label: string;
      onClick: () => void;
      danger?: boolean;
      disabled?: boolean;
    }[],
  ) =>
    items.length > 0 && (
      <Dropdown trigger={['click']} menu={{ items }}>
        <Button
          type="text"
          size="small"
          disabled={write.busy}
          aria-label="更多操作"
          icon={<EllipsisOutlined />}
        />
      </Dropdown>
    );
  const communityColumns = [
    {
      title: '小区',
      key: 'name',
      width: 210,
      render: (_: unknown, row: Community) => (
        <div>
          <Button
            type="link"
            style={{ padding: 0, fontWeight: 600 }}
            onClick={() => setDetail({ kind: 'community', id: row.id })}
          >
            {row.name}
          </Button>
          <div className="muted small">{row.code}</div>
        </div>
      ),
    },
    { title: '所属物业公司', dataIndex: 'property_company_name', width: 230 },
    { title: '小区地址', dataIndex: 'address', ellipsis: true, width: 260 },
    {
      title: '状态',
      width: 100,
      render: (_: unknown, row: Community) => enabledTag(row.enabled),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right' as const,
      render: (_: unknown, row: Community) => (
        <Space>
          <Button
            type="link"
            size="small"
            onClick={() => setDetail({ kind: 'community', id: row.id })}
          >
            查看
          </Button>
          {can('platform.onboarding.manage') && (
            <>
              <Button
                type="link"
                size="small"
                disabled={write.busy}
                onClick={() => setEdit({ kind: 'community', item: row })}
              >
                编辑
              </Button>
              {menu([
                {
                  key: 'toggle',
                  label: row.enabled ? '停用小区' : '启用小区',
                  danger: row.enabled,
                  onClick: () => toggleCommunity(row),
                },
              ])}
            </>
          )}
        </Space>
      ),
    },
  ];
  const companyContent = (
    <>
      <PageHeader
        title="物业公司"
        description="统一管理物业接入，清楚掌握公司、服务小区与账号状态。"
        extra={
          can('platform.onboarding.manage') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setEdit({ kind: 'company' })}
            >
              新建物业公司
            </Button>
          )
        }
      />
      <div className="stats-grid">
        <Metric
          label="合作物业公司"
          value={stats.data?.all ?? '—'}
          detail="平台已接入公司"
          icon={<BankOutlined />}
        />
        <Metric
          label="正常服务"
          value={stats.data?.active ?? '—'}
          detail="公司账号可正常登录"
          icon={<CheckCircleOutlined />}
        />
        <Metric
          label="服务小区"
          value={stats.data?.communities ?? '—'}
          detail={
            can('platform.onboarding.read')
              ? '已建立的小区档案'
              : '暂无小区读取权限'
          }
          icon={<ApartmentOutlined />}
        />
        <Metric
          label="待完成接入"
          value={stats.data ? stats.data.all - stats.data.active : '—'}
          detail="完成管理员开通后启用"
          icon={<TeamOutlined />}
        />
      </div>
      {stats.isError && (
        <Alert
          type="warning"
          showIcon
          title="统计加载失败"
          action={
            <Button size="small" onClick={() => void stats.refetch()}>
              重试
            </Button>
          }
          style={{ marginBottom: 18 }}
        />
      )}
      <Panel>
        <ListFilter
          value={params}
          placeholder={
            filterField === 'code' ? '搜索公司编码' : '搜索物业公司名称'
          }
          fieldOptions={[
            { value: 'name', label: '公司名称' },
            { value: 'code', label: '公司编码' },
          ]}
          onSearch={search}
          onReset={reset}
        />
        <ReadState
          error={companies.error}
          retry={() => void companies.refetch()}
        >
          <Table<Company>
            rowKey="id"
            loading={companies.isFetching}
            locale={{ emptyText: emptyList }}
            dataSource={companies.data?.items}
            pagination={pagination(companies.data, filters, (next) =>
              update({ page: String(next) }),
            )}
            scroll={{ x: 1040 }}
            columns={[
              {
                title: '物业公司',
                width: 290,
                render: (_, row) => (
                  <Space size={12}>
                    <Avatar
                      shape="square"
                      size={40}
                      style={{
                        background: '#3d64d814',
                        color: '#3d64d8',
                        fontWeight: 700,
                      }}
                    >
                      {row.name.slice(0, 2)}
                    </Avatar>
                    <div>
                      <Button
                        type="link"
                        style={{ padding: 0, fontWeight: 600 }}
                        onClick={() => openCompany(row)}
                      >
                        {row.name}
                      </Button>
                      <div className="muted small">{row.code}</div>
                    </div>
                  </Space>
                ),
              },
              {
                title: '联系人',
                width: 155,
                render: (_, row) => (
                  <div>
                    {row.contact_name || '—'}
                    <div className="muted small">
                      {row.contact_phone || '未填写电话'}
                    </div>
                  </div>
                ),
              },
              {
                title: '服务小区',
                width: 100,
                render: (_, row) => <CompanyCommunityCount id={row.id} />,
              },
              {
                title: '接入状态',
                width: 110,
                render: (_, row) => enabledTag(row.enabled),
              },
              {
                title: '创建时间',
                width: 150,
                render: (_, row) => time(row.created_at),
              },
              {
                title: '操作',
                width: 150,
                fixed: 'right',
                render: (_, row) => (
                  <Space>
                    <Button
                      type="link"
                      size="small"
                      onClick={() => setDetail({ kind: 'company', id: row.id })}
                    >
                      速览
                    </Button>
                    {(can('platform.onboarding.manage') ||
                      can('platform.onboarding.toggle')) && (
                      <>
                        {can('platform.onboarding.manage') && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() =>
                              setEdit({ kind: 'company', item: row })
                            }
                          >
                            编辑
                          </Button>
                        )}
                        {can('platform.onboarding.toggle') &&
                          menu([
                            {
                              key: 'status',
                              label: row.enabled ? '停用公司' : '启用公司',
                              danger: row.enabled,
                              onClick: () => toggleCompany(row),
                            },
                          ])}
                      </>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </ReadState>
      </Panel>
    </>
  );
  const c = company.data;
  const adminTable = (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="公司管理员可管理本公司全部小区，包含以后新增的小区。权限不会扩展到其他公司。"
      />
      <div style={{ textAlign: 'right', marginBottom: 16 }}>
        {can('platform.system.manage') && c && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setEdit({ kind: 'company-admin', company: c })}
          >
            开通公司管理员
          </Button>
        )}
      </div>
      <ReadState error={admins.error} retry={() => void admins.refetch()}>
        <Table<Account>
          rowKey="id"
          loading={admins.isFetching}
          locale={{ emptyText: emptyList }}
          dataSource={admins.data?.items}
          pagination={pagination(
            admins.data,
            { page: validPage(params.admin_page) },
            (next) => update({ admin_page: String(next) }),
          )}
          scroll={{ x: 760 }}
          columns={[
            {
              title: '管理员',
              width: 210,
              render: (_, row) => (
                <Person name={row.display_name} sub={row.login_name} />
              ),
            },
            {
              title: '角色与范围',
              width: 190,
              render: () => (
                <div>
                  <Tag color="blue">公司超级管理员</Tag>
                  <div className="muted small">本公司全部小区</div>
                </div>
              ),
            },
            {
              title: '状态',
              width: 100,
              render: (_, row) => enabledTag(row.enabled),
            },
            {
              title: '首次改密',
              width: 100,
              render: (_, row) =>
                row.must_change_password ? (
                  <Status color="orange">待修改</Status>
                ) : (
                  '已完成'
                ),
            },
            {
              title: '操作',
              width: 160,
              render: (_, row) => (
                <Space>
                  <Button
                    type="link"
                    size="small"
                    onClick={() =>
                      setDetail({
                        kind: 'company-admin',
                        id: row.id,
                        company: c,
                      })
                    }
                  >
                    查看
                  </Button>
                  {can('platform.system.manage') && (
                    <Button
                      type="link"
                      size="small"
                      onClick={() =>
                        setEdit({
                          kind: 'company-admin',
                          item: row,
                          company: c,
                        })
                      }
                    >
                      编辑
                    </Button>
                  )}
                  {menu([
                    ...(can('platform.system.manage')
                      ? [
                          {
                            key: 'reset',
                            label: '重置密码',
                            onClick: () =>
                              setEdit({
                                kind: 'company-admin',
                                item: row,
                                company: c,
                                action: 'reset' as const,
                              }),
                          },
                        ]
                      : []),
                    ...(can('platform.system.manage')
                      ? [
                          {
                            key: 'status',
                            label: row.enabled ? '停用账号' : '启用账号',
                            danger: row.enabled,
                            onClick: () => toggleAdmin(row),
                          },
                        ]
                      : []),
                  ])}
                </Space>
              ),
            },
          ]}
        />
      </ReadState>
    </>
  );
  const detailContent = (
    <ReadState
      error={company.error}
      loading={company.isPending}
      retry={() => void company.refetch()}
    >
      {c && (
        <>
          <PageHeader
            title={c.name}
            description={`${c.code} · ${c.contact_name || '未填写联系人'} · ${c.contact_phone || '未填写联系电话'}`}
            back={back}
            extra={
              <>
                {enabledTag(c.enabled)}
                {can('platform.onboarding.manage') && (
                  <Button
                    icon={<EditOutlined />}
                    onClick={() => setEdit({ kind: 'company', item: c })}
                  >
                    编辑资料
                  </Button>
                )}
                {can('platform.payment_config.read') && (
                  <Button
                    type="primary"
                    onClick={() =>
                      go('payment-configuration', { company: c.id })
                    }
                  >
                    收款配置 <ArrowRightOutlined />
                  </Button>
                )}
              </>
            }
          />
          {!c.enabled && (
            <Alert
              style={{ marginBottom: 18 }}
              type="warning"
              showIcon
              title="公司当前停用"
              description="可以维护资料、建立小区和开通管理员。至少有一名有效公司管理员后，方可启用物业账号登录。"
              action={
                can('platform.onboarding.toggle') && (
                  <Button onClick={() => toggleCompany(c)}>启用公司</Button>
                )
              }
            />
          )}
          <Panel title="基本资料">
            <DetailGrid
              items={[
                ['公司编码', c.code],
                ['联系人', c.contact_name],
                ['联系电话', c.contact_phone],
                ['创建时间', time(c.created_at)],
              ]}
            />
          </Panel>
          <Panel>
            {!can('platform.onboarding.read') &&
            !can('platform.system.read') ? (
              <Alert
                type="info"
                showIcon
                title="暂无关联小区和公司管理员的读取权限"
              />
            ) : (
              <Tabs
                activeKey={tab}
                onChange={(next) => update({ tab: next })}
                items={[
                  ...(can('platform.onboarding.read')
                    ? [
                        {
                          key: 'communities',
                          label: `关联小区 · ${detailCommunities.data?.total ?? '—'}`,
                          children: (
                            <>
                              <div
                                style={{
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  marginBottom: 16,
                                  alignItems: 'center',
                                }}
                              >
                                <Typography.Text type="secondary">
                                  当前公司的全部服务小区
                                </Typography.Text>
                                {can('platform.onboarding.manage') && (
                                  <Button
                                    icon={<PlusOutlined />}
                                    onClick={() =>
                                      setEdit({ kind: 'community', company: c })
                                    }
                                  >
                                    新增小区
                                  </Button>
                                )}
                              </div>
                              <ReadState
                                error={detailCommunities.error}
                                retry={() => void detailCommunities.refetch()}
                              >
                                <Table<Community>
                                  rowKey="id"
                                  loading={detailCommunities.isFetching}
                                  locale={{ emptyText: emptyList }}
                                  dataSource={detailCommunities.data?.items}
                                  pagination={pagination(
                                    detailCommunities.data,
                                    { page: validPage(params.community_page) },
                                    (next) =>
                                      update({ community_page: String(next) }),
                                  )}
                                  columns={communityColumns.filter(
                                    (column) => column.title !== '所属物业公司',
                                  )}
                                  scroll={{ x: 720 }}
                                />
                              </ReadState>
                            </>
                          ),
                        },
                      ]
                    : []),
                  ...(can('platform.system.read')
                    ? [
                        {
                          key: 'admins',
                          label: `公司管理员 · ${admins.data?.total ?? '—'}`,
                          children: adminTable,
                        },
                      ]
                    : []),
                ]}
              />
            )}
          </Panel>
        </>
      )}
    </ReadState>
  );
  const communitiesContent = (
    <>
      <PageHeader
        title="小区管理"
        description="管理全平台小区档案与物业归属，保留独立的小区启停状态。"
        extra={
          can('platform.onboarding.manage') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setEdit({ kind: 'community' })}
            >
              新建小区
            </Button>
          )
        }
      />
      <Panel>
        <ListFilter
          value={params}
          placeholder={filterField === 'code' ? '搜索小区编码' : '搜索小区名称'}
          fieldOptions={[
            { value: 'name', label: '小区名称' },
            { value: 'code', label: '小区编码' },
          ]}
          onSearch={search}
          onReset={reset}
        >
          {can('platform.onboarding.read') && (
            <CompanyPicker value={companyChoice} onChange={setCompanyChoice} />
          )}
        </ListFilter>
        <ReadState
          error={communities.error}
          retry={() => void communities.refetch()}
        >
          <Table<Community>
            rowKey="id"
            loading={communities.isFetching}
            locale={{ emptyText: emptyList }}
            dataSource={communities.data?.items}
            columns={communityColumns}
            pagination={pagination(communities.data, filters, (next) =>
              update({ page: String(next) }),
            )}
            scroll={{ x: 1000 }}
          />
        </ReadState>
      </Panel>
    </>
  );
  const save = async (values: Record<string, unknown>) => {
    if (!edit) return;
    if (edit.kind === 'company') {
      const data = {
        name: String(values.name).trim(),
        contact_name:
          typeof values.contact_name === 'string'
            ? values.contact_name.trim() || null
            : null,
        contact_phone:
          typeof values.contact_phone === 'string'
            ? values.contact_phone.trim() || null
            : null,
      };
      const result = await write.run(() =>
        edit.item
          ? api.updateCompany(edit.item.id, data)
          : api.createCompany({ ...data, code: String(values.code).trim() }),
      );
      if (!edit.item)
        setNotice({
          text: '物业公司已创建，请进入公司详情开通管理员，再启用服务。',
          company: result.id,
        });
    } else if (edit.kind === 'community') {
      const data = {
        name: String(values.name).trim(),
        address: String(values.address).trim(),
      };
      await write.run(() =>
        edit.item
          ? api.updateCommunity(edit.item.id, data)
          : api.createCommunity({
              ...data,
              property_company_id: String(values.property_company_id),
              code: String(values.code).trim(),
            }),
      );
    } else {
      const id = edit.company!.id;
      await write.run<unknown>(() =>
        edit.action === 'reset'
          ? api.resetCompanyAdminPassword(
              id,
              edit.item!.id,
              String(values.password),
            )
          : edit.item
            ? api.updateCompanyAdmin(id, edit.item.id, {
                display_name: String(values.display_name).trim(),
              })
            : api.createCompanyAdmin(id, {
                login_name: String(values.login_name).trim(),
                display_name: String(values.display_name).trim(),
                password: String(values.password),
              }),
      );
    }
    message.success(
      edit.action === 'reset' ? '临时密码已重置，原会话已失效' : '保存成功',
    );
  };
  let initialValues: Record<string, unknown> = {};
  if (edit?.kind === 'company') {
    const item = edit.item as Company | undefined;
    initialValues = item
      ? {
          code: item.code,
          name: item.name,
          contact_name: item.contact_name,
          contact_phone: item.contact_phone,
        }
      : {};
  } else if (edit?.kind === 'community') {
    const item = edit.item as Community | undefined;
    initialValues = item
      ? {
          code: item.code,
          name: item.name,
          address: item.address,
          property_company_id: item.property_company_id,
        }
      : { property_company_id: edit.company?.id || companyChoice };
  } else if (edit?.kind === 'company-admin' && edit.action !== 'reset') {
    const item = edit.item as Account | undefined;
    initialValues = item
      ? { login_name: item.login_name, display_name: item.display_name }
      : {};
  }
  if (
    (page === 'companies' || page === 'company-detail') &&
    !can('platform.onboarding.read') &&
    (can('platform.system.read') || can('platform.payment_config.read'))
  )
    return (
      <>
        <PageHeader
          title={companyLocator.data?.items[0]?.name || '公司业务查询'}
          description="选择公司后，只展示当前岗位获授权的业务区块。"
          back={page === 'company-detail' ? () => go('companies') : undefined}
        />
        <Panel>
          <CompanyPicker
            value={companyId}
            onChange={(value) =>
              value && go('company-detail', { company: value, tab: 'admins' })
            }
          />
        </Panel>
        {page === 'company-detail' && (
          <ReadState
            error={companyLocator.error}
            loading={companyLocator.isPending}
            retry={() => void companyLocator.refetch()}
          >
            {companyLocator.data?.items.length ? (
              <>
                {can('platform.payment_config.read') && (
                  <Panel>
                    <Button
                      type="primary"
                      onClick={() =>
                        go('payment-configuration', { company: companyId })
                      }
                    >
                      查看收款配置
                    </Button>
                  </Panel>
                )}
                {can('platform.system.read') && (
                  <Panel title="公司管理员">{adminTable}</Panel>
                )}
              </>
            ) : (
              <Alert type="info" title="公司不存在或不在授权范围内" />
            )}
          </ReadState>
        )}
      </>
    );
  const permission =
    page === 'companies' || page === 'company-detail'
      ? 'platform.onboarding.read'
      : 'platform.onboarding.read';
  if (!can(permission))
    return <ReadState error={new ApiError(403)} retry={() => undefined} />;
  if (page === 'company-detail' && !companyId)
    return (
      <Result
        status="404"
        title="请选择物业公司"
        extra={<Button onClick={back}>返回公司列表</Button>}
      />
    );
  return (
    <>
      {notice && (
        <Alert
          type="success"
          showIcon
          closable
          onClose={() => setNotice(undefined)}
          title={notice.text}
          action={
            notice.company && (
              <Button
                size="small"
                onClick={() =>
                  go('company-detail', {
                    company: notice.company,
                    tab: 'admins',
                  })
                }
              >
                进入公司详情
              </Button>
            )
          }
          style={{ marginBottom: 18 }}
        />
      )}
      {page === 'companies'
        ? companyContent
        : page === 'company-detail'
          ? detailContent
          : communitiesContent}
      {edit && (
        <PlatformFormDialog
          key={`${edit.kind}-${edit.item?.id || 'new'}-${edit.action || 'edit'}`}
          title={
            edit.kind === 'company'
              ? edit.item
                ? '编辑物业公司'
                : '新建物业公司'
              : edit.kind === 'community'
                ? edit.item
                  ? '编辑小区'
                  : '新建小区'
                : edit.action === 'reset'
                  ? '重置临时密码'
                  : edit.item
                    ? '编辑公司管理员'
                    : '开通公司管理员'
          }
          initialValues={initialValues}
          onClose={() => setEdit(undefined)}
          onSubmit={save}
          okText={edit.action === 'reset' ? '确认重置' : '保存'}
          render={(form) =>
            edit.kind === 'company' ? (
              <>
                {!edit.item && (
                  <Alert
                    style={{ marginBottom: 18 }}
                    type="info"
                    showIcon
                    title="新公司默认为停用。开通公司管理员后，再启用服务。"
                  />
                )}
                <Form.Item name="code" label="公司编码" rules={codeRules}>
                  <Input
                    disabled={!!edit.item}
                    placeholder="如 WY2026005，创建后不可修改"
                    maxLength={64}
                  />
                </Form.Item>
                <Form.Item
                  name="name"
                  label="公司名称"
                  rules={[...required, { max: 160 }]}
                >
                  <Input placeholder="请输入工商登记名称" maxLength={160} />
                </Form.Item>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: 16,
                  }}
                >
                  <Form.Item
                    name="contact_name"
                    label="联系人"
                    rules={[{ max: 80 }]}
                  >
                    <Input maxLength={80} />
                  </Form.Item>
                  <Form.Item
                    name="contact_phone"
                    label="联系电话"
                    rules={[{ max: 32 }]}
                  >
                    <Input maxLength={32} />
                  </Form.Item>
                </div>
              </>
            ) : edit.kind === 'community' ? (
              <>
                {edit.item || edit.company ? (
                  <>
                    <Form.Item name="property_company_id" hidden>
                      <Input />
                    </Form.Item>
                    <Form.Item label="所属物业公司">
                      <Input
                        readOnly
                        value={
                          edit.company?.name ||
                          (edit.item as Community).property_company_name
                        }
                      />
                    </Form.Item>
                  </>
                ) : (
                  <Form.Item
                    name="property_company_id"
                    label="所属物业公司"
                    rules={[{ required: true, message: '请选择物业公司' }]}
                  >
                    <CompanyPicker />
                  </Form.Item>
                )}
                <Form.Item name="code" label="小区编码" rules={codeRules}>
                  <Input
                    disabled={!!edit.item}
                    placeholder="创建后不可修改"
                    maxLength={64}
                  />
                </Form.Item>
                <Form.Item
                  name="name"
                  label="小区名称"
                  rules={[...required, { max: 160 }]}
                >
                  <Input maxLength={160} />
                </Form.Item>
                <Form.Item
                  name="address"
                  label="小区地址"
                  rules={[...required, { max: 255 }]}
                >
                  <Input.TextArea rows={2} maxLength={255} showCount />
                </Form.Item>
              </>
            ) : (
              <>
                <Alert
                  style={{ marginBottom: 18 }}
                  type="info"
                  showIcon
                  title={`所属公司：${edit.company!.name}`}
                  description="管理本公司全部小区，包括后续新增小区。"
                />
                {(edit.action === 'reset' || !edit.item) && (
                  <Alert
                    style={{ marginBottom: 18 }}
                    type="warning"
                    showIcon
                    title="初始或重置密码均须首次登录修改"
                    description={
                      edit.action === 'reset'
                        ? '提交后，该账号所有原有会话立即失效。'
                        : '请通过安全渠道交付临时密码，并提醒管理员首次登录修改。'
                    }
                  />
                )}
                {edit.action !== 'reset' && (
                  <>
                    <Form.Item
                      name="login_name"
                      label="登录名"
                      rules={loginRules}
                    >
                      <Input
                        disabled={!!edit.item}
                        autoComplete="off"
                        placeholder="字母、数字及 _.@-"
                        maxLength={64}
                      />
                    </Form.Item>
                    <Form.Item
                      name="display_name"
                      label="显示名称"
                      rules={[...required, { max: 80 }]}
                    >
                      <Input maxLength={80} />
                    </Form.Item>
                  </>
                )}
                {(edit.action === 'reset' || !edit.item) && (
                  <PasswordFields form={form} />
                )}
              </>
            )
          }
        />
      )}
      {detail && (
        <PlatformDetail
          detail={detail}
          onClose={() => setDetail(undefined)}
          go={go}
        />
      )}
    </>
  );
}
