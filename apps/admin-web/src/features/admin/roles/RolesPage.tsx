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
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';

import { useAdminSession } from '../../../auth/use-admin-session';
import type { Role } from '../../../shared/admin-api';
import {
  useAdminApi,
  useAdminOperation,
  useDirtyForm,
  useListState,
} from '../hooks';
import { applyFormErrors } from '../form-utils';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';

type Mode = { kind: 'create' | 'view' | 'edit' | 'permissions'; id?: string };

function RoleEditor({
  mode,
  role,
  done,
  closeRef,
}: {
  mode: Mode;
  role?: Role;
  done: () => void;
  closeRef: RefObject<() => void>;
}) {
  const api = useAdminApi(),
    { status, hasPermission } = useAdminSession();
  const [form] = Form.useForm();
  const dirty = useDirtyForm(),
    operation = useAdminOperation();
  const close = useCallback(() => {
    if (!operation.isPending) dirty.close(done);
  }, [dirty, done, operation.isPending]);
  useEffect(() => {
    closeRef.current = close;
  }, [closeRef, close]);
  const catalog = useQuery({
    queryKey: ['permissions'],
    queryFn: api.permissions,
    enabled:
      mode.kind === 'permissions' &&
      status === 'authenticated' &&
      hasPermission('admin.role.read'),
  });
  const groups = [
    ...new Set(catalog.data?.map((permission) => permission.group) ?? []),
  ];
  if (mode.kind === 'permissions' && catalog.isError)
    return <ReadError retry={() => void catalog.refetch()} />;
  return (
    <>
      <OperationError error={operation.error} />
      <Form
        name={`role-${mode.kind}-${role?.id || 'new'}`}
        form={form}
        layout="vertical"
        initialValues={role ?? {}}
        onValuesChange={dirty.changed}
        onFinish={async (values: {
          code: string;
          name: string;
          permissions: string[];
        }) => {
          if (operation.isPending) return;
          try {
            await operation.mutateAsync({
              security: mode.kind === 'permissions',
              run: () =>
                mode.kind === 'create'
                  ? api.createRole({ code: values.code, name: values.name })
                  : mode.kind === 'edit'
                    ? api.updateRole(role!.id, { name: values.name })
                    : api.assignPermissions(role!.id, values.permissions),
            });
            dirty.reset();
            form.resetFields();
            operation.reset();
            done();
          } catch (error) {
            applyFormErrors(form, error, ['code', 'name', 'permissions']);
          }
        }}
      >
        {mode.kind === 'permissions' ? (
          <>
            <Alert
              showIcon
              type="warning"
              title="权限保存后，关联账号需要重新登录。"
              style={{ marginBottom: 16 }}
            />
            <Form.Item name="permissions" label="角色权限">
              <Checkbox.Group style={{ display: 'block' }}>
                {groups.map((group) => (
                  <div key={group} style={{ marginBottom: 20 }}>
                    <Typography.Text strong>{group}</Typography.Text>
                    <div style={{ marginTop: 8 }}>
                      {catalog.data
                        ?.filter((permission) => permission.group === group)
                        .map((permission) => (
                          <div
                            key={permission.code}
                            style={{ marginBottom: 8 }}
                          >
                            <Checkbox
                              value={permission.code}
                              disabled={!permission.assignable}
                            >
                              {permission.name}
                              {permission.assignable ? '' : '（仅超级管理员）'}
                            </Checkbox>
                          </div>
                        ))}
                    </div>
                  </div>
                ))}
              </Checkbox.Group>
            </Form.Item>
          </>
        ) : (
          <>
            <Form.Item
              name="code"
              label="角色编码"
              rules={[
                { required: true },
                { max: 64 },
                {
                  pattern: /^[a-z][a-z0-9_]*$/,
                  message: '使用小写字母、数字和下划线，首字符为字母',
                },
              ]}
            >
              <Input readOnly={mode.kind === 'edit'} />
            </Form.Item>
            <Form.Item
              name="name"
              label="角色名称"
              rules={[{ required: true }, { min: 1, max: 80 }]}
            >
              <Input />
            </Form.Item>
          </>
        )}
        <Space>
          <Button
            type="primary"
            htmlType="submit"
            loading={operation.isPending}
            disabled={mode.kind === 'permissions' && !catalog.data}
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
function RoleDrawer({ mode, done }: { mode: Mode; done: () => void }) {
  const api = useAdminApi();
  const closeRef = useRef<() => void>(done);
  const query = useQuery({
    queryKey: ['roles', mode.id],
    queryFn: () => api.role(mode.id!),
    enabled: !!mode.id,
  });
  const title = {
    create: '创建角色',
    view: '角色详情',
    edit: '编辑角色',
    permissions: '配置权限',
  }[mode.kind];
  return (
    <Drawer
      open
      title={title}
      size={560}
      destroyOnHidden
      onClose={() => closeRef.current()}
    >
      {query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : mode.id && !query.data ? (
        <ProTable loading search={false} pagination={false} />
      ) : (mode.kind === 'view' || query.data?.is_system) && query.data ? (
        <>
          {query.data.is_system && (
            <Alert
              type="info"
              title="系统角色固定，拥有本后台完整权限，不可修改。"
              style={{ marginBottom: 16 }}
            />
          )}
          <Descriptions
            column={1}
            items={[
              { key: 'code', label: '角色编码', children: query.data.code },
              { key: 'name', label: '名称', children: query.data.name },
              {
                key: 'status',
                label: '状态',
                children: query.data.enabled ? '启用' : '停用',
              },
              {
                key: 'permissions',
                label: '权限',
                children: query.data.permissions.map((code) => (
                  <Tag key={code}>{code}</Tag>
                )),
              },
            ]}
          />
        </>
      ) : (
        <RoleEditor
          mode={mode}
          role={query.data}
          closeRef={closeRef}
          done={done}
        />
      )}
    </Drawer>
  );
}
export default function RolesPage() {
  const api = useAdminApi(),
    state = useListState(),
    { status, hasPermission } = useAdminSession();
  const { modal } = App.useApp();
  const [mode, setMode] = useState<Mode | null>(null),
    operation = useAdminOperation();
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    name: state.params.get('name') || undefined,
    enabled: ['true', 'false'].includes(state.params.get('enabled') || '')
      ? state.params.get('enabled') === 'true'
      : undefined,
  };
  const query = useQuery({
    queryKey: ['roles', filters],
    queryFn: () => api.roles(filters),
    enabled: status === 'authenticated' && hasPermission('admin.role.read'),
  });
  const columns: ProColumns<Role>[] = [
    { title: '编码', dataIndex: 'code' },
    { title: '名称', dataIndex: 'name' },
    {
      title: '状态',
      render: (_, row) => (
        <Tag color={row.enabled ? 'green' : undefined}>
          {row.enabled ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '类型',
      render: (_, row) =>
        row.is_system ? <Tag color="blue">系统角色</Tag> : '普通角色',
    },
    {
      title: '权限概要',
      render: (_, row) => `${row.permissions.length} 项权限`,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 320,
      render: (_, row) => (
        <Space wrap>
          <Button
            type="link"
            onClick={() => setMode({ kind: 'view', id: row.id })}
          >
            详情
          </Button>
          {hasPermission('admin.role.update') && (
            <>
              <Button
                type="link"
                disabled={row.is_system}
                onClick={() => setMode({ kind: 'edit', id: row.id })}
              >
                编辑
              </Button>
              <Button
                type="link"
                disabled={row.is_system || operation.isPending}
                danger={row.enabled}
                onClick={() =>
                  modal.confirm({
                    title: `${row.enabled ? '停用' : '启用'} ${row.name}？`,
                    content: '关联账号需要重新登录。',
                    onOk: () =>
                      operation
                        .mutateAsync({
                          run: () =>
                            api.updateRole(row.id, { enabled: !row.enabled }),
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
          {hasPermission('admin.role.assign_permissions') && (
            <Button
              type="link"
              disabled={row.is_system}
              onClick={() => setMode({ kind: 'permissions', id: row.id })}
            >
              配置权限
            </Button>
          )}
        </Space>
      ),
    },
  ];
  return (
    <PageContainer title="角色管理">
      <OperationError error={operation.error} />
      <Form
        name="role-search"
        key={`${filters.name}-${filters.enabled}`}
        layout="inline"
        style={{ marginBottom: 16 }}
        initialValues={{
          name: filters.name,
          enabled:
            filters.enabled === undefined ? undefined : String(filters.enabled),
        }}
        onFinish={(values: { name?: string; enabled?: string }) =>
          state.update({ ...values, page: 1 })
        }
      >
        <Form.Item name="name" label="角色名称">
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
              state.update({ name: undefined, enabled: undefined, page: 1 })
            }
          >
            重置
          </Button>
        </Space>
      </Form>
      {query.isError && <ReadError retry={() => void query.refetch()} />}
      <ProTable<Role>
        rowKey="id"
        columns={columns}
        search={false}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 1000 }}
        options={{ reload: () => void query.refetch() }}
        locale={{
          emptyText: (
            <ListEmpty
              filtered={!!filters.name || filters.enabled !== undefined}
            />
          ),
        }}
        toolBarRender={() =>
          hasPermission('admin.role.create')
            ? [
                <Button
                  key="create"
                  type="primary"
                  onClick={() => setMode({ kind: 'create' })}
                >
                  创建角色
                </Button>,
              ]
            : []
        }
      />
      {mode && (
        <RoleDrawer
          key={`${mode.kind}-${mode.id}`}
          mode={mode}
          done={() => setMode(null)}
        />
      )}
    </PageContainer>
  );
}
