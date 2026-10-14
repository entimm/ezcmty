import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from 'react';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Tag,
} from 'antd';

import { usePlatformSession } from '../hooks';
import type { Account, RoleSummary } from '../../../shared/api/admin';
import { usePlatformAdminApi, usePlatformAdminOperation } from '../hooks';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import { useListState } from '../../../shared/hooks/use-list-state';
import { applyFormErrors, passwordFields } from '../../../shared/form-utils';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';

type Mode = {
  kind: 'create' | 'view' | 'edit' | 'roles' | 'reset';
  id?: string;
};

function RolePicker({
  current,
  protectedId,
  form,
  changed,
}: {
  current: RoleSummary[];
  protectedId?: string;
  form: ReturnType<typeof Form.useForm>[0];
  changed: () => void;
}) {
  const api = usePlatformAdminApi(),
    { status, hasPermission } = usePlatformSession();
  const query = useInfiniteQuery({
    queryKey: ['roles', 'options'],
    queryFn: ({ pageParam }) =>
      api.roles({ enabled: true, page: pageParam, page_size: 100 }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled: status === 'authenticated' && hasPermission('admin.role.read'),
  });
  const choices = new Map(current.map((role) => [role.id, role]));
  for (const page of query.data?.pages ?? [])
    for (const role of page.items) choices.set(role.id, role);
  const options = [...choices.values()].map((role) => ({
    value: role.id,
    label: `${role.name}${role.enabled ? '' : '（停用）'}`,
    disabled: !role.enabled || role.id === protectedId,
  }));
  return (
    <>
      {query.isError && <ReadError retry={() => void query.refetch()} />}
      <Form.Item
        name="role_ids"
        label="角色"
        normalize={(ids: string[]) =>
          protectedId && !ids.includes(protectedId)
            ? [...ids, protectedId]
            : ids
        }
      >
        <Select
          mode="multiple"
          loading={query.isFetching}
          options={options}
          optionFilterProp="label"
          placeholder="可不分配角色"
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
      {current.some((role) => !role.enabled) && (
        <Alert
          type="info"
          showIcon
          title="已分配的停用角色可以保留或移除，不能新增停用角色。"
          style={{ marginBottom: 16 }}
        />
      )}
      {protectedId && (
        <Alert
          type="info"
          showIcon
          title="不能撤销本人超级管理员资格。"
          style={{ marginBottom: 16 }}
        />
      )}
      {query.hasNextPage && (
        <Button
          style={{ marginBottom: 16 }}
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          加载更多角色
        </Button>
      )}
    </>
  );
}

function AccountEditor({
  mode,
  account,
  done,
  closeRef,
}: {
  mode: Mode;
  account?: Account;
  done: () => void;
  closeRef: RefObject<() => void>;
}) {
  const api = usePlatformAdminApi(),
    { session } = usePlatformSession();
  const [form] = Form.useForm();
  const operation = usePlatformAdminOperation(),
    dirty = useDirtyForm();
  const close = useCallback(() => {
    if (!operation.isPending) dirty.close(done);
  }, [dirty, done, operation.isPending]);
  useEffect(() => {
    closeRef.current = close;
  }, [closeRef, close]);
  const protectedId =
    account?.id === session?.subjectId
      ? account?.roles.find((role) => role.code === 'super_admin')?.id
      : undefined;
  const initial = {
    login_name: account?.login_name,
    display_name: account?.display_name,
    role_ids: account?.roles.map((role) => role.id) ?? [],
  };
  return (
    <>
      <OperationError error={operation.error} />
      <Form
        name={`account-${mode.kind}-${account?.id || 'new'}`}
        form={form}
        layout="vertical"
        initialValues={initial}
        onValuesChange={dirty.changed}
        onFinish={async (values: {
          login_name: string;
          display_name: string;
          password: string;
          role_ids: string[];
        }) => {
          if (operation.isPending) return;
          try {
            await operation.mutateAsync({
              security: mode.kind === 'roles' || mode.kind === 'reset',
              run: () => {
                if (mode.kind === 'create')
                  return api.createAccount({
                    login_name: values.login_name,
                    display_name: values.display_name,
                    password: values.password,
                    role_ids: values.role_ids,
                  });
                if (mode.kind === 'edit')
                  return api.updateAccount(account!.id, {
                    display_name: values.display_name,
                  });
                if (mode.kind === 'roles')
                  return api.assignRoles(account!.id, values.role_ids);
                return api.resetPassword(account!.id, values.password);
              },
            });
            form.resetFields();
            dirty.reset();
            operation.reset();
            done();
          } catch (error) {
            applyFormErrors(form, error, [
              'login_name',
              'display_name',
              'password',
              'role_ids',
            ]);
          }
        }}
      >
        {(mode.kind === 'create' || mode.kind === 'edit') && (
          <>
            <Form.Item
              name="login_name"
              label="登录名"
              rules={[
                { required: true },
                { max: 64 },
                {
                  pattern: /^[A-Za-z0-9][A-Za-z0-9_.@-]*$/,
                  message: '使用字母、数字及 _.@-，首字符为字母或数字',
                },
              ]}
            >
              <Input readOnly={mode.kind === 'edit'} autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="display_name"
              label="显示名称"
              rules={[{ required: true }, { min: 1, max: 80 }]}
            >
              <Input />
            </Form.Item>
          </>
        )}
        {(mode.kind === 'create' || mode.kind === 'reset') && (
          <>
            <Alert
              type="info"
              showIcon
              title="初始或重置密码要求首次登录修改，旧会话将失效。"
              style={{ marginBottom: 16 }}
            />
            {passwordFields(
              form,
              'password',
              mode.kind === 'create' ? '初始密码' : '临时密码',
            )}
          </>
        )}
        {(mode.kind === 'create' || mode.kind === 'roles') && (
          <RolePicker
            current={account?.roles ?? []}
            protectedId={protectedId}
            form={form}
            changed={dirty.changed}
          />
        )}
        <Space>
          <Button
            type="primary"
            htmlType="submit"
            loading={operation.isPending}
          >
            保存
          </Button>
          <Button disabled={operation.isPending} onClick={close}>
            取消
          </Button>
        </Space>
      </Form>
    </>
  );
}

function AccountDrawer({ mode, done }: { mode: Mode; done: () => void }) {
  const api = usePlatformAdminApi();
  const query = useQuery({
    queryKey: ['accounts', mode.id],
    queryFn: () => api.account(mode.id!),
    enabled: !!mode.id,
  });
  const closeRef = useRef<() => void>(done);
  const title = {
    create: '创建管理员',
    view: '管理员详情',
    edit: '编辑管理员',
    roles: '分配角色',
    reset: '重置密码',
  }[mode.kind];
  return (
    <Drawer
      open
      title={title}
      size={520}
      destroyOnHidden
      onClose={() => closeRef.current()}
    >
      {query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : mode.id && !query.data ? (
        <ProTable loading search={false} pagination={false} />
      ) : mode.kind === 'view' && query.data ? (
        <Descriptions
          column={1}
          items={[
            { key: 'login', label: '登录名', children: query.data.login_name },
            {
              key: 'name',
              label: '显示名称',
              children: query.data.display_name,
            },
            {
              key: 'status',
              label: '状态',
              children: query.data.enabled ? '启用' : '停用',
            },
            {
              key: 'roles',
              label: '角色',
              children: query.data.roles.map((role) => (
                <Tag key={role.id}>
                  {role.name}
                  {role.enabled ? '' : '（停用）'}
                </Tag>
              )),
            },
            {
              key: 'password',
              label: '需要改密',
              children: query.data.must_change_password ? '是' : '否',
            },
            {
              key: 'time',
              label: '创建时间',
              children: new Date(query.data.created_at).toLocaleString(),
            },
          ]}
        />
      ) : (
        <AccountEditor
          mode={mode}
          account={query.data}
          done={done}
          closeRef={closeRef}
        />
      )}
    </Drawer>
  );
}

export default function AccountsPage() {
  const api = usePlatformAdminApi(),
    state = useListState(),
    { status, session, hasPermission } = usePlatformSession();
  const { modal } = App.useApp();
  const [mode, setMode] = useState<Mode | null>(null);
  const operation = usePlatformAdminOperation();
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    login_name: state.params.get('login_name') || undefined,
    enabled: ['true', 'false'].includes(state.params.get('enabled') || '')
      ? state.params.get('enabled') === 'true'
      : undefined,
  };
  const query = useQuery({
    queryKey: ['accounts', filters],
    queryFn: () => api.accounts(filters),
    enabled: status === 'authenticated' && hasPermission('admin.account.read'),
  });
  const columns: ProColumns<Account>[] = [
    { title: '登录名', dataIndex: 'login_name' },
    { title: '显示名称', dataIndex: 'display_name' },
    {
      title: '状态',
      dataIndex: 'enabled',
      render: (_, row) => (
        <Tag color={row.enabled ? 'green' : undefined}>
          {row.enabled ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '角色',
      dataIndex: 'roles',
      render: (_, row) =>
        row.roles.map((role) => (
          <Tag key={role.id}>
            {role.name}
            {role.enabled ? '' : '（停用）'}
          </Tag>
        )),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (_, row) => new Date(row.created_at).toLocaleString(),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 360,
      render: (_, row) => (
        <Space wrap>
          <Button
            type="link"
            onClick={() => setMode({ kind: 'view', id: row.id })}
          >
            详情
          </Button>
          {hasPermission('admin.account.update') && (
            <>
              <Button
                type="link"
                onClick={() => setMode({ kind: 'edit', id: row.id })}
              >
                编辑
              </Button>
              <Button
                type="link"
                danger={row.enabled}
                disabled={
                  operation.isPending ||
                  (row.id === session?.subjectId && row.enabled)
                }
                title={
                  row.id === session?.subjectId ? '不能停用本人账号' : undefined
                }
                onClick={() =>
                  modal.confirm({
                    title: `${row.enabled ? '停用' : '启用'} ${row.login_name}？`,
                    content: '状态变化会使该账号旧会话失效，停用期间无法登录。',
                    onOk: () =>
                      operation
                        .mutateAsync({
                          run: () =>
                            api.updateAccount(row.id, {
                              enabled: !row.enabled,
                            }),
                          security: true,
                        })
                        .then(() => undefined),
                  })
                }
              >
                {row.enabled ? '停用' : '启用'}
              </Button>
            </>
          )}
          {hasPermission('admin.account.assign_roles') && (
            <Button
              type="link"
              onClick={() => setMode({ kind: 'roles', id: row.id })}
            >
              分配角色
            </Button>
          )}
          {hasPermission('admin.account.reset_password') && (
            <Button
              type="link"
              disabled={row.id === session?.subjectId}
              onClick={() => setMode({ kind: 'reset', id: row.id })}
            >
              重置密码
            </Button>
          )}
        </Space>
      ),
    },
  ];
  return (
    <PageContainer title="管理员管理">
      <OperationError error={operation.error} />
      <Form
        name="account-search"
        key={`${filters.login_name}-${filters.enabled}`}
        layout="inline"
        style={{ marginBottom: 16 }}
        initialValues={{
          login_name: filters.login_name,
          enabled:
            filters.enabled === undefined ? undefined : String(filters.enabled),
        }}
        onFinish={(values: { login_name?: string; enabled?: string }) =>
          state.update({ ...values, page: 1 })
        }
      >
        <Form.Item name="login_name" label="登录名">
          <Input allowClear />
        </Form.Item>
        <Form.Item name="enabled" label="状态">
          <Select
            allowClear
            style={{ width: 120 }}
            options={[
              { value: 'true', label: '启用' },
              { value: 'false', label: '停用' },
            ]}
          />
        </Form.Item>
        <Space>
          <Button type="primary" htmlType="submit">
            查询
          </Button>
          <Button
            onClick={() =>
              state.update({
                login_name: undefined,
                enabled: undefined,
                page: 1,
              })
            }
          >
            重置
          </Button>
        </Space>
      </Form>
      {query.isError && <ReadError retry={() => void query.refetch()} />}
      <ProTable<Account>
        rowKey="id"
        columns={columns}
        search={false}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 1050 }}
        options={{
          reload: () => void query.refetch(),
          density: true,
          setting: true,
        }}
        locale={{
          emptyText: (
            <ListEmpty
              filtered={!!filters.login_name || filters.enabled !== undefined}
            />
          ),
        }}
        toolBarRender={() =>
          hasPermission('admin.account.create')
            ? [
                <Button
                  key="create"
                  type="primary"
                  onClick={() => setMode({ kind: 'create' })}
                >
                  创建管理员
                </Button>,
              ]
            : []
        }
      />
      {mode && (
        <AccountDrawer
          key={`${mode.kind}-${mode.id}`}
          mode={mode}
          done={() => setMode(null)}
        />
      )}
    </PageContainer>
  );
}
