import { useEffect, useState, type ReactNode } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import {
  Alert,
  App,
  Button,
  DatePicker,
  Descriptions,
  Divider,
  Drawer,
  Dropdown,
  Form,
  Input,
  Modal,
  Result,
  Select,
  Space,
  Table,
  Tag,
  Tree,
  Typography,
} from 'antd';
import {
  EllipsisOutlined,
  LockOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useAdmin } from '../../shared/context';
import { DetailGrid, PageHeader, Panel, Status } from '../../shared/ui';
import {
  type Account,
  type Audit,
  type Filters,
  type Permission,
  type Role,
} from './api';
import {
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
import type { PlatformPagesProps } from './PlatformPages';

type Edit = {
  kind: 'account' | 'role';
  item?: Account | Role;
  action?: 'roles' | 'reset' | 'permissions';
};
type Detail = { kind: 'account' | 'role'; id: string };
const required = [{ required: true, whitespace: true, message: '请填写此项' }];
const enabledTag = (enabled: boolean) => (
  <Status>{enabled ? '启用' : '已停用'}</Status>
);
const validPage = (value?: string) =>
  /^[1-9]\d{0,6}$/.test(value || '') ? Number(value) : 1;
const actionNames: Record<string, string> = {
  'account.create': '创建管理员',
  'account.update': '调整管理员资料或状态',
  'account.assign_roles': '分配管理员角色',
  'account.password_reset': '重置管理员密码',
  'account.initialize': '初始化管理员',
  'account.profile_update': '修改本人资料',
  'account.password_change': '修改本人密码',
  'session.login': '管理员登录',
  'session.logout': '管理员退出',
  'role.create': '创建角色',
  'role.update': '调整角色资料或状态',
  'role.assign_permissions': '配置角色权限',
  'admin.account.create': '创建管理员',
  'admin.account.update': '调整管理员资料或状态',
  'admin.account.assign_roles': '分配管理员角色',
  'admin.account.reset_password': '重置管理员密码',
  'admin.role.create': '创建角色',
  'admin.role.update': '调整角色资料或状态',
  'admin.role.assign_permissions': '配置角色权限',
  'property.company.create': '创建物业公司',
  'property.company.update': '调整物业公司',
  'property.community.create': '创建小区',
  'property.community.update': '调整小区',
  'property.admin.create': '开通公司管理员',
  'property.admin.update': '调整公司管理员',
  'property.admin.reset_password': '重置公司管理员密码',
  'property.admin.password_reset': '重置公司管理员密码',
  'payment.payment_order.recover': '安排支付单恢复',
  'payment.reconciliation_run.recover': '安排核对批次恢复',
  'payment.reconciliation_discrepancy.recover': '安排核对差异恢复',
  'payment.reconciliation_discrepancy.external_resolution': '记录外部处置',
  'platform.payment_funds.recover': '安排资金恢复',
  'platform.payment_config.manage': '调整收款配置',
};
const objectNames: Record<string, string> = {
  account: '管理员',
  role: '角色',
  property_company: '物业公司',
  community: '小区',
  payment_order: '支付单',
  reconciliation_run: '核对批次',
  reconciliation_discrepancy: '核对差异',
  session: '会话',
};
const metadataNames: Record<string, string> = {
  changed_fields: '修改字段',
  role_ids: '角色标识',
  permissions: '授予权限',
  reason: '处理原因',
  task_id: '处理任务',
  evidence: '核实依据',
  evidence_reference: '依据引用',
  before: '变更前',
  after: '变更后',
  source_request_id: '来源请求标识',
  source_digest: '来源摘要',
  status: '状态',
  resolved_by: '处理人标识',
  name: '名称',
  display_name: '显示名称',
  enabled: '启停状态',
  contact_name: '联系人',
  contact_phone: '联系电话',
  address: '地址',
  match_status: '匹配结果',
  house_id: '房屋标识',
};
function auditValue(value: unknown): ReactNode {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value))
    return value.length
      ? value
          .map((item) =>
            typeof item === 'string'
              ? metadataNames[item] || item
              : String(item),
          )
          .join('、')
      : '无';
  if (typeof value === 'object')
    return (
      <Descriptions
        column={1}
        size="small"
        items={Object.entries(value).map(([key, item]) => ({
          key,
          label: metadataNames[key] || key,
          children: auditValue(item),
        }))}
      />
    );
  const statuses: Record<string, string> = {
    resolved: '已解决',
    pending: '待处理',
    success: '成功',
    failure: '失败',
    approved: '已通过',
    rejected: '已拒绝',
  };
  return statuses[String(value)] || String(value);
}
function wallClock(value: string) {
  const milliseconds = new Date(value).getTime();
  return Number.isNaN(milliseconds)
    ? null
    : dayjs(new Date(milliseconds + 8 * 3600000).toISOString().slice(0, 19));
}
function instant(value: Dayjs) {
  return new Date(value.format('YYYY-MM-DDTHH:mm:ss') + '+08:00').toISOString();
}

function SystemDetail({
  detail,
  onClose,
}: {
  detail: Detail;
  onClose: () => void;
}) {
  const api = usePlatformApi();
  const query = useQuery<Account | Role>({
    queryKey: ['platform', 'system-detail', detail.kind, detail.id],
    queryFn: () =>
      detail.kind === 'account' ? api.account(detail.id) : api.role(detail.id),
  });
  const catalog = useQuery({
    queryKey: ['platform', 'permissions'],
    queryFn: api.permissions,
    enabled: detail.kind === 'role',
  });
  const item = query.data;
  let fields: [string, ReactNode][] = [];
  if (item && detail.kind === 'account') {
    const account = item as Account;
    fields = [
      ['显示名称', account.display_name],
      ['登录名', account.login_name],
      ['账号状态', enabledTag(account.enabled)],
      ['首次改密', account.must_change_password ? '需要修改' : '已完成'],
      ['创建时间', time(account.created_at)],
      ['所属后台', '平台后台'],
    ];
  } else if (item) {
    const role = item as Role;
    fields = [
      ['角色名称', role.name],
      ['角色编码', role.code],
      ['类型', role.is_system ? '系统内置' : '自定义角色'],
      ['状态', enabledTag(role.enabled)],
    ];
  }
  return (
    <Modal
      open
      title={detail.kind === 'account' ? '管理员详情' : '角色详情'}
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
            <Divider />
            <Typography.Text strong>
              {detail.kind === 'account'
                ? '已分配角色'
                : `权限明细 · ${(item as Role).permissions.length} 项`}
            </Typography.Text>
            <div
              style={{
                marginTop: 12,
                display: 'flex',
                gap: 8,
                flexWrap: 'wrap',
              }}
            >
              {detail.kind === 'account'
                ? (item as Account).roles.length
                  ? (item as Account).roles.map((role) => (
                      <Tag key={role.id}>
                        {role.name}
                        {role.enabled ? '' : ' · 停用'}
                      </Tag>
                    ))
                  : '未分配角色'
                : (item as Role).permissions.map((permission) => (
                    <Tag key={permission}>
                      {catalog.data?.find((entry) => entry.code === permission)
                        ?.name || permission}
                    </Tag>
                  ))}
            </div>
            {detail.kind === 'role' && (item as Role).is_system && (
              <Alert
                style={{ marginTop: 16 }}
                type="info"
                title="系统角色固定，不允许修改。"
              />
            )}
          </>
        )}
      </ReadState>
    </Modal>
  );
}

function RolePicker({
  item,
  form,
  changed,
}: {
  item?: Account;
  form: ReturnType<typeof Form.useForm>[0];
  changed: () => void;
}) {
  const api = usePlatformApi(),
    { can, session } = useAdmin();
  const query = useInfiniteQuery({
    queryKey: ['platform', 'role-options'],
    queryFn: ({ pageParam }) =>
      api.roles({ page: pageParam, page_size: 100, enabled: true }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled: can('admin.role.read'),
  });
  const selected = new Map((item?.roles ?? []).map((role) => [role.id, role]));
  for (const page of query.data?.pages ?? [])
    for (const role of page.items) selected.set(role.id, role);
  const protectedId =
    item?.id === session?.subjectId
      ? item.roles.find((role) => role.code === 'super_admin')?.id
      : undefined;
  return (
    <>
      <ReadState error={query.error} retry={() => void query.refetch()}>
        <Form.Item
          name="role_ids"
          label="分配角色"
          normalize={(ids: string[]) =>
            protectedId && !ids.includes(protectedId)
              ? [...ids, protectedId]
              : ids
          }
        >
          <Select
            mode="multiple"
            loading={query.isFetching}
            placeholder="可暂不分配角色"
            optionFilterProp="label"
            options={[...selected.values()].map((role) => ({
              value: role.id,
              label: role.name + (role.enabled ? '' : '（停用，可移除）'),
              disabled: !role.enabled || role.id === protectedId,
            }))}
            tagRender={({ value, label }) => (
              <Tag
                closable={value !== protectedId}
                onClose={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  form.setFieldValue(
                    'role_ids',
                    (form.getFieldValue('role_ids') as string[]).filter(
                      (id) => id !== value,
                    ),
                  );
                  changed();
                }}
              >
                {label}
              </Tag>
            )}
          />
        </Form.Item>
      </ReadState>
      {query.hasNextPage && (
        <Button
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
          style={{ marginBottom: 16 }}
        >
          加载更多角色
        </Button>
      )}
      {protectedId && (
        <Typography.Text type="secondary">
          系统会保护本人超级管理员资格。
        </Typography.Text>
      )}
    </>
  );
}

function PermissionTree({
  permissions,
  form,
  changed,
}: {
  permissions: Permission[];
  form: ReturnType<typeof Form.useForm>[0];
  changed: () => void;
}) {
  const selected: string[] = Form.useWatch('permissions', form) ?? [];
  return (
    <>
      <Form.Item name="permissions" hidden>
        <Input />
      </Form.Item>
      <Tree
        checkable
        selectable={false}
        defaultExpandAll
        checkedKeys={selected}
        onCheck={(keys) => {
          const checked = Array.isArray(keys) ? keys : keys.checked;
          form.setFieldValue(
            'permissions',
            checked.filter((key) =>
              permissions.some(
                (permission) =>
                  permission.code === key && permission.assignable,
              ),
            ),
          );
          changed();
        }}
        treeData={[
          ...new Set(permissions.map((permission) => permission.group)),
        ].map((group, index) => ({
          key: 'group-' + index,
          title: <strong>{group}</strong>,
          children: permissions
            .filter((permission) => permission.group === group)
            .map((permission) => ({
              key: permission.code,
              title: (
                <span>
                  {permission.name}
                  {!permission.assignable && (
                    <Typography.Text type="secondary">
                      {' '}
                      · 仅超级管理员
                    </Typography.Text>
                  )}
                </span>
              ),
              disableCheckbox: !permission.assignable,
            })),
        }))}
      />
      <Divider style={{ margin: '16px 0 0' }} />
      <Typography.Text type="secondary">
        已选择 {selected.length} 项权限
      </Typography.Text>
    </>
  );
}

export function SystemPages({ page, params, go }: PlatformPagesProps) {
  const api = usePlatformApi(),
    { can, session } = useAdmin(),
    { message, modal } = App.useApp();
  const write = usePlatformWrite();
  const [edit, setEdit] = useState<Edit>(),
    [detail, setDetail] = useState<Detail>(),
    [auditDetail, setAuditDetail] = useState<Audit>(),
    [notice, setNotice] = useState('');
  const [auditSearch, setAuditSearch] = useState(params.search || ''),
    [auditField, setAuditField] = useState(params.field || 'action'),
    [auditResult, setAuditResult] = useState(params.result);
  const [dates, setDates] = useState<[Dayjs | null, Dayjs | null] | null>(
    params.from_time && params.to_time
      ? [wallClock(params.from_time), wallClock(params.to_time)]
      : null,
  );
  useEffect(() => {
    setDetail(undefined);
    setAuditDetail(undefined);
    setNotice('');
  }, [page]);
  useEffect(() => {
    setAuditSearch(params.search || '');
    setAuditField(params.field || 'action');
    setAuditResult(params.result);
    setDates(
      params.from_time && params.to_time
        ? [wallClock(params.from_time), wallClock(params.to_time)]
        : null,
    );
  }, [
    params.search,
    params.field,
    params.result,
    params.from_time,
    params.to_time,
  ]);
  const update = (values: Record<string, string | undefined>) =>
    go(page, { ...params, ...values });
  const filters: Filters = {
    page: validPage(params.page),
    page_size: 8,
    enabled:
      params.enabled === 'true'
        ? true
        : params.enabled === 'false'
          ? false
          : undefined,
  };
  if (page === 'accounts') filters.login_name = params.search || undefined;
  else if (page === 'roles') filters.name = params.search || undefined;
  else {
    filters[params.field === 'request_id' ? 'request_id' : 'action'] =
      params.search || undefined;
    filters.result = params.result;
    filters.from_time = params.from_time;
    filters.to_time = params.to_time;
    delete filters.enabled;
  }
  const accounts = useQuery({
    queryKey: ['platform', 'accounts', filters],
    queryFn: () => api.accounts(filters),
    enabled: page === 'accounts' && can('admin.account.read'),
  });
  const roles = useQuery({
    queryKey: ['platform', 'roles', filters],
    queryFn: () => api.roles(filters),
    enabled: page === 'roles' && can('admin.role.read'),
  });
  const audits = useQuery({
    queryKey: ['platform', 'audit', filters],
    queryFn: () => api.audit(filters),
    enabled: page === 'audit' && can('admin.audit.read'),
  });
  const catalog = useQuery({
    queryKey: ['platform', 'permissions'],
    queryFn: api.permissions,
    enabled:
      edit?.kind === 'role' &&
      edit.action === 'permissions' &&
      can('admin.role.read'),
  });
  const confirm = (
    title: string,
    content: string,
    run: () => Promise<unknown>,
  ) =>
    modal.confirm({
      title,
      content,
      okText: '确认操作',
      cancelText: '取消',
      onOk: async () => {
        try {
          await write.run(run, true);
          message.success('操作已完成');
        } catch (error) {
          message.error(errorText(error));
          throw error;
        }
      },
    });
  const menu = (
    items: {
      key: string;
      label: string;
      onClick: () => void;
      disabled?: boolean;
      danger?: boolean;
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
  const commonSearch = (values: Record<string, string | undefined>) =>
    update({ ...values, page: undefined });
  const accountContent = (
    <>
      <PageHeader
        title="平台管理员"
        description="管理平台账号与角色。账号授权仅在平台后台生效。"
        extra={
          can('admin.account.create') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setEdit({ kind: 'account' })}
            >
              新建管理员
            </Button>
          )
        }
      />
      <Panel>
        <ListFilter
          value={params}
          placeholder="搜索登录名"
          onSearch={commonSearch}
          onReset={() => go(page)}
        />
        <ReadState error={accounts.error} retry={() => void accounts.refetch()}>
          <Table<Account>
            rowKey="id"
            loading={accounts.isFetching}
            locale={{ emptyText: emptyList }}
            dataSource={accounts.data?.items}
            pagination={pagination(accounts.data, filters, (next) =>
              update({ page: String(next) }),
            )}
            scroll={{ x: 850 }}
            columns={[
              {
                title: '管理员',
                width: 210,
                render: (_, row) => (
                  <Person name={row.display_name} sub={row.login_name} />
                ),
              },
              {
                title: '角色',
                width: 230,
                render: (_, row) =>
                  row.roles.length ? (
                    row.roles.map((role) => (
                      <Tag
                        key={role.id}
                        color={role.code === 'super_admin' ? 'blue' : 'default'}
                      >
                        {role.name}
                        {role.enabled ? '' : ' · 停用'}
                      </Tag>
                    ))
                  ) : (
                    <Typography.Text type="secondary">
                      未分配角色
                    </Typography.Text>
                  ),
              },
              {
                title: '状态',
                width: 100,
                render: (_, row) => enabledTag(row.enabled),
              },
              {
                title: '创建时间',
                width: 160,
                render: (_, row) => time(row.created_at),
              },
              {
                title: '操作',
                width: 160,
                fixed: 'right',
                render: (_, row) => (
                  <Space>
                    <Button
                      type="link"
                      size="small"
                      onClick={() => setDetail({ kind: 'account', id: row.id })}
                    >
                      查看
                    </Button>
                    {can('admin.account.update') && (
                      <Button
                        type="link"
                        size="small"
                        onClick={() => setEdit({ kind: 'account', item: row })}
                      >
                        编辑
                      </Button>
                    )}
                    {menu([
                      ...(can('admin.account.assign_roles')
                        ? [
                            {
                              key: 'roles',
                              label: '分配角色',
                              onClick: () =>
                                setEdit({
                                  kind: 'account',
                                  item: row,
                                  action: 'roles' as const,
                                }),
                            },
                          ]
                        : []),
                      ...(can('admin.account.reset_password')
                        ? [
                            {
                              key: 'reset',
                              label: '重置密码',
                              disabled: row.id === session?.subjectId,
                              onClick: () =>
                                setEdit({
                                  kind: 'account',
                                  item: row,
                                  action: 'reset' as const,
                                }),
                            },
                          ]
                        : []),
                      ...(can('admin.account.update')
                        ? [
                            {
                              key: 'toggle',
                              label: row.enabled ? '停用账号' : '启用账号',
                              disabled: row.id === session?.subjectId,
                              danger: row.enabled,
                              onClick: () =>
                                confirm(
                                  `${row.enabled ? '停用' : '启用'} ${row.display_name}？`,
                                  '状态变化会使该账号旧会话失效，停用期间不能登录。',
                                  () =>
                                    api.updateAccount(row.id, {
                                      enabled: !row.enabled,
                                    }),
                                ),
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
      </Panel>
    </>
  );
  const rolesContent = (
    <>
      <PageHeader
        title="角色与权限"
        description="按岗位配置业务权限；管理员与角色管理写权限仅限系统超级管理员。"
        extra={
          can('admin.role.create') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setEdit({ kind: 'role' })}
            >
              新建角色
            </Button>
          )
        }
      />
      <Panel>
        <ListFilter
          value={params}
          placeholder="搜索角色名称"
          onSearch={commonSearch}
          onReset={() => go(page)}
        />
        <ReadState error={roles.error} retry={() => void roles.refetch()}>
          <Table<Role>
            rowKey="id"
            loading={roles.isFetching}
            locale={{ emptyText: emptyList }}
            dataSource={roles.data?.items}
            pagination={pagination(roles.data, filters, (next) =>
              update({ page: String(next) }),
            )}
            scroll={{ x: 820 }}
            columns={[
              {
                title: '角色名称',
                width: 230,
                render: (_, row) => (
                  <Space>
                    <SafetyCertificateOutlined
                      style={{
                        color: row.is_system ? '#4f67dc' : '#8b96a7',
                        fontSize: 20,
                      }}
                    />
                    <div>
                      <strong>{row.name}</strong>
                      <div className="muted small">{row.code}</div>
                    </div>
                  </Space>
                ),
              },
              {
                title: '类型',
                width: 130,
                render: (_, row) =>
                  row.is_system ? (
                    <Tag color="blue">系统内置</Tag>
                  ) : (
                    '自定义角色'
                  ),
              },
              {
                title: '权限概要',
                width: 130,
                render: (_, row) => `${row.permissions.length} 项权限`,
              },
              {
                title: '状态',
                width: 100,
                render: (_, row) => enabledTag(row.enabled),
              },
              {
                title: '操作',
                width: 220,
                fixed: 'right',
                render: (_, row) => (
                  <Space>
                    <Button
                      type="link"
                      size="small"
                      onClick={() => setDetail({ kind: 'role', id: row.id })}
                    >
                      查看
                    </Button>
                    {!row.is_system && (
                      <>
                        {can('admin.role.assign_permissions') && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() =>
                              setEdit({
                                kind: 'role',
                                item: row,
                                action: 'permissions',
                              })
                            }
                          >
                            配置权限
                          </Button>
                        )}
                        {can('admin.role.update') &&
                          menu([
                            {
                              key: 'edit',
                              label: '编辑资料',
                              onClick: () =>
                                setEdit({ kind: 'role', item: row }),
                            },
                            {
                              key: 'toggle',
                              label: row.enabled ? '停用角色' : '启用角色',
                              danger: row.enabled,
                              onClick: () =>
                                confirm(
                                  `${row.enabled ? '停用' : '启用'}「${row.name}」？`,
                                  '该角色关联的管理员需要重新登录，旧会话失效。',
                                  () =>
                                    api.updateRole(row.id, {
                                      enabled: !row.enabled,
                                    }),
                                ),
                            },
                          ])}
                      </>
                    )}
                    {row.is_system && (
                      <Typography.Text
                        type="secondary"
                        style={{ fontSize: 12 }}
                      >
                        <LockOutlined /> 不可修改
                      </Typography.Text>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </ReadState>
      </Panel>
      <Alert
        type="info"
        showIcon
        title="系统角色拥有本后台完整权限，不能编辑、启停或修改权限。普通角色只能分配目录中允许授予的业务及查询权限。"
      />
    </>
  );
  const auditContent = (
    <>
      <PageHeader
        title="审计日志"
        description="追踪平台操作与关键变更，关联请求标识定位问题。时间显示与查询均按北京时间。"
      />
      <Panel>
        <div className="filter-bar">
          <Select
            aria-label="审计搜索字段"
            style={{ width: 118 }}
            value={auditField}
            onChange={setAuditField}
            options={[
              { value: 'action', label: '操作类型' },
              { value: 'request_id', label: '请求标识' },
            ]}
          />
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder={
              auditField === 'request_id'
                ? '输入请求标识'
                : '输入操作类型，如 account.create'
            }
            value={auditSearch}
            onChange={(event) => setAuditSearch(event.target.value)}
            style={{ width: 280 }}
          />
          <DatePicker.RangePicker
            showTime
            value={dates}
            onChange={setDates}
            style={{ width: 350 }}
          />
          <Select
            allowClear
            aria-label="审计结果"
            value={auditResult}
            onChange={setAuditResult}
            style={{ width: 125 }}
            placeholder="全部结果"
            options={[
              { value: 'success', label: '成功' },
              { value: 'failure', label: '失败' },
            ]}
          />
          <div className="filter-actions">
            <Button
              type="primary"
              onClick={() =>
                update({
                  search: auditSearch.trim() || undefined,
                  field: auditField,
                  result: auditResult,
                  from_time: dates?.[0] ? instant(dates[0]) : undefined,
                  to_time: dates?.[1] ? instant(dates[1]) : undefined,
                  page: undefined,
                })
              }
            >
              查询
            </Button>
            <Button onClick={() => go(page)}>重置</Button>
          </div>
        </div>
        <ReadState error={audits.error} retry={() => void audits.refetch()}>
          <Table<Audit>
            rowKey="id"
            loading={audits.isFetching}
            locale={{ emptyText: emptyList }}
            dataSource={audits.data?.items}
            pagination={pagination(audits.data, filters, (next) =>
              update({ page: String(next) }),
            )}
            scroll={{ x: 1100 }}
            columns={[
              {
                title: '操作时间',
                width: 175,
                render: (_, row) => time(row.created_at),
              },
              {
                title: '操作者',
                width: 100,
                render: (_, row) => row.actor_name || '系统',
              },
              {
                title: '操作',
                width: 190,
                render: (_, row) => (
                  <div>
                    {actionNames[row.action] || row.action}
                    <div className="muted small">
                      {actionNames[row.action] ? row.action : ''}
                    </div>
                  </div>
                ),
              },
              {
                title: '操作对象',
                width: 220,
                ellipsis: true,
                render: (_, row) =>
                  `${objectNames[row.target_type] || row.target_type} · ${row.target_id || '—'}`,
              },
              {
                title: '结果',
                width: 90,
                render: (_, row) => (
                  <Status>{row.result === 'success' ? '成功' : '失败'}</Status>
                ),
              },
              {
                title: '请求标识',
                width: 190,
                ellipsis: true,
                render: (_, row) => (
                  <Typography.Text
                    copyable
                    style={{ fontSize: 12, color: '#7b889b' }}
                  >
                    {row.request_id}
                  </Typography.Text>
                ),
              },
              {
                title: '操作',
                width: 80,
                fixed: 'right',
                render: (_, row) => (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => setAuditDetail(row)}
                  >
                    详情
                  </Button>
                ),
              },
            ]}
          />
        </ReadState>
      </Panel>
    </>
  );
  const save = async (values: Record<string, unknown>) => {
    if (!edit) return;
    if (edit.kind === 'account') {
      if (edit.action === 'roles')
        await write.run(
          () => api.assignRoles(edit.item!.id, values.role_ids as string[]),
          true,
        );
      else if (edit.action === 'reset')
        await write.run(
          () => api.resetPassword(edit.item!.id, String(values.password)),
          true,
        );
      else if (edit.item)
        await write.run(
          () =>
            api.updateAccount(edit.item!.id, {
              display_name: String(values.display_name).trim(),
            }),
          edit.item.id === session.subjectId,
        );
      else
        await write.run(() =>
          api.createAccount({
            login_name: String(values.login_name).trim(),
            display_name: String(values.display_name).trim(),
            password: String(values.password),
            role_ids: (values.role_ids as string[]) || [],
          }),
        );
    } else {
      if (edit.action === 'permissions') {
        if (!catalog.data) throw new Error('权限目录尚未加载，请重试');
        await write.run(
          () =>
            api.assignPermissions(
              edit.item!.id,
              (values.permissions as string[]).filter((code) =>
                catalog.data.some(
                  (permission) =>
                    permission.code === code && permission.assignable,
                ),
              ),
            ),
          true,
        );
      } else if (edit.item)
        await write.run(() =>
          api.updateRole(edit.item!.id, { name: String(values.name).trim() }),
        );
      else {
        await write.run(() =>
          api.createRole({
            code: String(values.code).trim(),
            name: String(values.name).trim(),
          }),
        );
        setNotice('角色已创建，尚未授予权限。请点击「配置权限」完成授权。');
      }
    }
    message.success(
      edit.action === 'reset' ? '临时密码已重置，原会话已失效' : '保存成功',
    );
  };
  let initialValues: Record<string, unknown> = {};
  if (edit?.kind === 'account') {
    const account = edit.item as Account | undefined;
    initialValues =
      edit.action === 'roles'
        ? { role_ids: account!.roles.map((role) => role.id) }
        : edit.action === 'reset'
          ? {}
          : account
            ? {
                login_name: account.login_name,
                display_name: account.display_name,
              }
            : { role_ids: [] };
  } else if (edit?.kind === 'role') {
    const role = edit.item as Role | undefined;
    initialValues =
      edit.action === 'permissions'
        ? { permissions: role!.permissions }
        : role
          ? { code: role.code, name: role.name }
          : {};
  }
  const permission =
    page === 'accounts'
      ? 'admin.account.read'
      : page === 'roles'
        ? 'admin.role.read'
        : 'admin.audit.read';
  if (!can(permission))
    return (
      <Result
        status="403"
        title="暂无访问权限"
        subTitle="请联系管理员确认当前账号的授权范围。"
      />
    );
  return (
    <>
      {notice && (
        <Alert
          type="success"
          closable
          showIcon
          onClose={() => setNotice('')}
          title={notice}
          style={{ marginBottom: 18 }}
        />
      )}
      {page === 'accounts'
        ? accountContent
        : page === 'roles'
          ? rolesContent
          : auditContent}
      {edit && (
        <PlatformFormDialog
          key={`${edit.kind}-${edit.item?.id || 'new'}-${edit.action || 'edit'}`}
          title={
            edit.kind === 'role'
              ? edit.action === 'permissions'
                ? `配置权限 · ${(edit.item as Role).name}`
                : edit.item
                  ? '编辑角色资料'
                  : '新建角色'
              : edit.action === 'roles'
                ? '分配管理员角色'
                : edit.action === 'reset'
                  ? '重置临时密码'
                  : edit.item
                    ? '编辑管理员'
                    : '新建平台管理员'
          }
          width={edit.action === 'permissions' ? 680 : 540}
          initialValues={initialValues}
          onClose={() => setEdit(undefined)}
          onSubmit={save}
          okText={
            edit.action === 'permissions'
              ? '保存权限'
              : edit.action === 'reset'
                ? '确认重置'
                : '保存'
          }
          render={(form, changed) =>
            edit.kind === 'account' ? (
              <>
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
                {edit.action !== 'roles' && edit.action !== 'reset' && (
                  <>
                    <Form.Item
                      name="login_name"
                      label="登录名"
                      rules={[
                        { required: true, message: '请输入登录名' },
                        {
                          pattern: /^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$/,
                          message: '使用 1–64 位字母、数字及 _.@-',
                        },
                      ]}
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
                {(edit.action === 'roles' || !edit.item) && (
                  <>
                    {edit.action === 'roles' && (
                      <Alert
                        style={{ marginBottom: 16 }}
                        type="info"
                        title="角色变更后，该账号需要重新登录。"
                      />
                    )}
                    <RolePicker
                      item={edit.item as Account | undefined}
                      form={form}
                      changed={changed}
                    />
                  </>
                )}
              </>
            ) : edit.action === 'permissions' ? (
              <>
                <Alert
                  style={{ marginBottom: 18 }}
                  type="warning"
                  showIcon
                  title="权限保存后，关联账号需要重新登录"
                  description="灰色权限仅属于系统超级管理员，不能分配给普通角色。"
                />
                <ReadState
                  error={catalog.error}
                  loading={catalog.isPending}
                  retry={() => void catalog.refetch()}
                >
                  {catalog.data && (
                    <PermissionTree
                      permissions={catalog.data}
                      form={form}
                      changed={changed}
                    />
                  )}
                </ReadState>
              </>
            ) : (
              <>
                <Form.Item
                  name="code"
                  label="角色编码"
                  rules={[
                    { required: true, message: '请输入角色编码' },
                    {
                      pattern: /^[a-z][a-z0-9_]{0,63}$/,
                      message: '小写字母开头，可用数字和下划线，最长 64 位',
                    },
                  ]}
                >
                  <Input
                    disabled={!!edit.item}
                    placeholder="如 finance_reviewer"
                    maxLength={64}
                  />
                </Form.Item>
                <Form.Item
                  name="name"
                  label="角色名称"
                  rules={[...required, { max: 80 }]}
                >
                  <Input maxLength={80} />
                </Form.Item>
                {!edit.item && (
                  <Alert
                    type="info"
                    showIcon
                    title="创建后，可在列表中继续配置该角色的权限。"
                  />
                )}
              </>
            )
          }
        />
      )}
      {detail && (
        <SystemDetail detail={detail} onClose={() => setDetail(undefined)} />
      )}
      <Drawer
        open={!!auditDetail}
        title="审计详情"
        size={560}
        onClose={() => setAuditDetail(undefined)}
      >
        {auditDetail && (
          <>
            <Alert
              type={auditDetail.result === 'success' ? 'success' : 'error'}
              showIcon
              title={`${actionNames[auditDetail.action] || auditDetail.action} · ${auditDetail.result === 'success' ? '成功' : '失败'}`}
              style={{ marginBottom: 24 }}
            />
            <Descriptions
              column={1}
              bordered
              size="small"
              items={[
                ['操作时间', time(auditDetail.created_at) + '（北京时间）'],
                ['操作人', auditDetail.actor_name || '系统'],
                [
                  '操作对象',
                  `${objectNames[auditDetail.target_type] || auditDetail.target_type} · ${auditDetail.target_id || '—'}`,
                ],
                ['所属后台', '平台后台'],
                ['操作类型', auditDetail.action],
                [
                  '请求标识',
                  <Typography.Text copyable>
                    {auditDetail.request_id}
                  </Typography.Text>,
                ],
              ].map(([label, children], index) => ({
                key: index,
                label,
                children,
              }))}
            />
            <Divider />
            <Typography.Title level={5}>变更说明</Typography.Title>
            {Object.keys(auditDetail.metadata).length ? (
              <Descriptions
                column={1}
                size="small"
                style={{ marginBottom: 20, wordBreak: 'break-word' }}
                items={Object.entries(auditDetail.metadata).map(
                  ([key, value]) => ({
                    key,
                    label: metadataNames[key] || key,
                    children: auditValue(value),
                  }),
                )}
              />
            ) : (
              <Typography.Paragraph>
                操作已完成，按平台允许公开的字段记录。
              </Typography.Paragraph>
            )}
            <Alert
              type="info"
              showIcon
              title="审计记录不包含密码、Cookie 或会话凭据。"
            />
          </>
        )}
      </Drawer>
    </>
  );
}
