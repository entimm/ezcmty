import { useState } from 'react';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Space,
  Spin,
  Tag,
} from 'antd';
import { useAdminSession } from '../../../auth/use-admin-session';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';
import type {
  PropertyAdmin,
  PropertyAdminCreate,
  PropertyCompany,
} from '../../../shared/admin-api/property';
import { passwordFields } from '../form-utils';
import { useListState } from '../hooks';
import { parseEnabled, usePropertyApi, usePropertyOperation } from './hooks';
import { PropertyFormDrawer } from './PropertyFormDrawer';
import { ResourceSearch } from './ResourceSearch';

type Mode = { action: 'create' | 'edit' | 'reset' | 'view'; id?: string };

function AdminDrawer({
  company,
  mode,
  done,
}: {
  company: PropertyCompany;
  mode: Mode;
  done: () => void;
}) {
  const api = usePropertyApi();
  const { status, hasPermission } = useAdminSession();
  const query = useQuery({
    queryKey: ['property-admins', company.id, 'detail', mode.id],
    queryFn: () => api.admin(company.id, mode.id!),
    enabled:
      !!mode.id &&
      status === 'authenticated' &&
      hasPermission('property.admin.read'),
  });
  if (mode.action === 'view')
    return (
      <Drawer
        open
        title="公司管理员详情"
        size={520}
        onClose={done}
        destroyOnHidden
      >
        {query.isPending ? (
          <Spin />
        ) : query.isError ? (
          <ReadError error={query.error} retry={() => void query.refetch()} />
        ) : (
          <Descriptions
            column={1}
            bordered
            items={[
              {
                key: 'login',
                label: '登录名',
                children: query.data.login_name,
              },
              {
                key: 'display',
                label: '显示名称',
                children: query.data.display_name,
              },
              { key: 'company', label: '所属公司', children: company.name },
              {
                key: 'enabled',
                label: '状态',
                children: query.data.enabled ? '启用' : '停用',
              },
              {
                key: 'password',
                label: '需要改密',
                children: query.data.must_change_password ? '是' : '否',
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
              { key: 'scope', label: '管理范围', children: '本公司全部小区' },
              {
                key: 'time',
                label: '创建时间',
                children: new Date(query.data.created_at).toLocaleString(),
              },
            ]}
          />
        )}
      </Drawer>
    );
  return (
    <PropertyFormDrawer<PropertyAdminCreate>
      title={
        mode.action === 'create'
          ? '开通公司管理员'
          : mode.action === 'edit'
            ? '编辑公司管理员'
            : '重置公司管理员密码'
      }
      loading={!!mode.id && query.isPending}
      error={mode.id ? query.error : undefined}
      retry={() => void query.refetch()}
      initialValues={query.data}
      done={done}
      fields={['login_name', 'display_name', 'password']}
      security={mode.action === 'reset'}
      save={(values) =>
        mode.action === 'create'
          ? api.createAdmin(company.id, {
              login_name: values.login_name,
              display_name: values.display_name,
              password: values.password,
            })
          : mode.action === 'edit'
            ? api.updateAdmin(company.id, mode.id!, {
                display_name: values.display_name,
              })
            : api.resetAdminPassword(company.id, mode.id!, values.password)
      }
    >
      {(form) => (
        <>
          <Form.Item label="所属物业公司">
            <Input readOnly value={company.name} />
          </Form.Item>
          <Alert
            type="info"
            showIcon
            title={
              mode.action === 'reset'
                ? '重置后旧会话失效，目标账号需要重新登录并修改密码。'
                : '公司管理员可以管理本公司全部小区，包括以后新增的小区。'
            }
            style={{ marginBottom: 16 }}
          />
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
            <Input readOnly={mode.action !== 'create'} autoComplete="off" />
          </Form.Item>
          {mode.action !== 'reset' && (
            <Form.Item
              name="display_name"
              label="显示名称"
              rules={[{ required: true, whitespace: true }, { max: 80 }]}
            >
              <Input />
            </Form.Item>
          )}
          {(mode.action === 'create' || mode.action === 'reset') && (
            <>
              {mode.action === 'create' && (
                <Alert
                  type="info"
                  title="初始密码需要在首次登录时修改。"
                  style={{ marginBottom: 16 }}
                />
              )}
              {passwordFields(
                form,
                'password',
                mode.action === 'create' ? '初始密码' : '临时密码',
              )}
            </>
          )}
        </>
      )}
    </PropertyFormDrawer>
  );
}

export function CompanyAdmins({ company }: { company: PropertyCompany }) {
  const api = usePropertyApi(),
    state = useListState('admins_');
  const { status, hasPermission } = useAdminSession();
  const { modal } = App.useApp();
  const [mode, setMode] = useState<Mode | null>(null);
  const operation = usePropertyOperation();
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    login_name: state.params.get('login_name') || undefined,
    enabled: parseEnabled(state.params.get('enabled')),
  };
  const query = useQuery({
    queryKey: ['property-admins', company.id, 'list', filters],
    queryFn: () => api.admins(company.id, filters),
    enabled: status === 'authenticated' && hasPermission('property.admin.read'),
  });
  const columns: ProColumns<PropertyAdmin>[] = [
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
        row.roles.map((role) => <Tag key={role.id}>{role.name}</Tag>),
    },
    {
      title: '需要改密',
      dataIndex: 'must_change_password',
      render: (_, row) => (row.must_change_password ? '是' : '否'),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (_, row) => new Date(row.created_at).toLocaleString(),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 320,
      render: (_, row) => (
        <Space wrap>
          <Button
            type="link"
            onClick={() => setMode({ action: 'view', id: row.id })}
          >
            详情
          </Button>
          {hasPermission('property.admin.update') && (
            <>
              <Button
                type="link"
                disabled={operation.isPending}
                onClick={() => setMode({ action: 'edit', id: row.id })}
              >
                编辑
              </Button>
              <Button
                type="link"
                danger={row.enabled}
                disabled={operation.isPending}
                onClick={() =>
                  modal.confirm({
                    title: `${row.enabled ? '停用' : '启用'} ${row.login_name}？`,
                    content:
                      '该账号旧会话将失效，停用期间不能登录。公司必须保留至少一名有效超级管理员。',
                    onOk: () =>
                      operation
                        .mutateAsync({
                          run: () =>
                            api.updateAdmin(company.id, row.id, {
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
          {hasPermission('property.admin.reset_password') && (
            <Button
              type="link"
              disabled={operation.isPending}
              onClick={() => setMode({ action: 'reset', id: row.id })}
            >
              重置密码
            </Button>
          )}
        </Space>
      ),
    },
  ];
  return (
    <>
      <OperationError error={operation.error} />
      <ResourceSearch
        admin
        values={filters}
        submit={(values) => state.update({ ...values, page: 1 })}
        reset={() =>
          state.update({ login_name: undefined, enabled: undefined, page: 1 })
        }
      />
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      <ProTable<PropertyAdmin>
        headerTitle="公司管理员"
        rowKey="id"
        columns={columns}
        search={false}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 1100 }}
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
          hasPermission('property.admin.create')
            ? [
                <Button
                  key="create"
                  type="primary"
                  onClick={() => setMode({ action: 'create' })}
                >
                  开通公司管理员
                </Button>,
              ]
            : []
        }
      />
      {mode && (
        <AdminDrawer
          key={`${mode.action}-${mode.id ?? 'new'}`}
          company={company}
          mode={mode}
          done={() => setMode(null)}
        />
      )}
    </>
  );
}
