import { Link } from '@umijs/max';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Form, Input, Select, Space } from 'antd';
import { ListEmpty, ReadError } from '../../../components/AdminFeedback';
import { useAdminApp } from '../../../shared/admin-app-context';
import { useListState } from '../../../shared/hooks/use-list-state';
import { usePropertySession, usePropertyWorkspaceApi } from '../hooks';
import { CommunityPicker } from '../housing/CommunityPicker';
import { HousePicker } from '../billing/HousePicker';
import type { Claim, HouseBinding } from './api';
import { useHouseClaimsApi } from './hooks';
import { MatchStatus, RecordStatus } from './Parts';
import { bindingLabels, claimLabels, maskPhone } from './values';

interface SearchValues {
  house_id?: string;
  status: string;
  match_status?: string;
  created_from?: string;
  created_to?: string;
  sort: string;
}
const localTime = (value?: string) => {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return undefined;
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};

export function RecordsPage({ kind }: { kind: 'claims' | 'bindings' }) {
  const claims = kind === 'claims';
  const resource = claims ? 'house-claims' : 'resident-house-bindings';
  const permission = claims
    ? 'property.house_claim.read'
    : 'property.resident_house_binding.read';
  const title = claims ? '房屋认领审核' : '居民房屋绑定';
  const labels = claims ? claimLabels : bindingLabels;
  const defaultStatus = claims ? 'pending' : 'active';
  const state = useListState();
  const api = useHouseClaimsApi();
  const workspace = usePropertyWorkspaceApi();
  const { status, hasPermission } = usePropertySession();
  const { path } = useAdminApp();
  const selectedStatus = state.params.get('status') ?? defaultStatus;
  const filterStatus =
    selectedStatus === 'all'
      ? undefined
      : selectedStatus in labels
        ? selectedStatus
        : defaultStatus;
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    community_id: state.params.get('community_id') || undefined,
    house_id: state.params.get('house_id') || undefined,
    status: filterStatus,
    match_status:
      claims &&
      ['matched', 'unmatched'].includes(state.params.get('match_status') ?? '')
        ? state.params.get('match_status')!
        : undefined,
    created_from: state.params.get('created_from') || undefined,
    created_to: state.params.get('created_to') || undefined,
    sort:
      state.params.get('sort') === 'created_at' ? 'created_at' : '-created_at',
  };
  const query = useQuery({
    queryKey: [resource, 'list', filters],
    queryFn: async () =>
      claims ? await api.claims(filters) : await api.bindings(filters),
    enabled: status === 'authenticated' && hasPermission(permission),
  });
  const community = useQuery({
    queryKey: ['communities', 'detail', filters.community_id],
    queryFn: () => workspace.community(filters.community_id!),
    enabled:
      !!filters.community_id &&
      status === 'authenticated' &&
      hasPermission('property.community.read'),
  });
  const columns: ProColumns<Claim | HouseBinding>[] = [
    { title: '房屋', dataIndex: 'house_label_snapshot', width: 260 },
    { title: '申请人', dataIndex: 'applicant_name' },
    { title: '手机号', render: (_, row) => maskPhone(row.applicant_phone) },
    { title: '状态', render: (_, row) => <RecordStatus status={row.status} /> },
    ...(claims
      ? [
          {
            title: '历史匹配',
            render: (_: unknown, row: Claim | HouseBinding) =>
              'match_status' in row ? (
                <MatchStatus matched={row.match_status === 'matched'} />
              ) : null,
          },
        ]
      : [
          {
            title: '当前权限',
            render: (_: unknown, row: Claim | HouseBinding) =>
              'effective_enabled' in row && row.effective_enabled
                ? '可使用'
                : '不可使用',
          },
        ]),
    {
      title: claims ? '申请时间' : '授予时间',
      dataIndex: claims ? 'created_at' : 'granted_at',
      valueType: 'dateTime',
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => (
        <Link to={path(`/property/${resource}/${row.id}`)}>查看详情</Link>
      ),
    },
  ];
  return (
    <PageContainer title={title} breadcrumb={{ items: [{ title }] }}>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <CommunityPicker
            value={filters.community_id}
            community={community.data}
            onChange={(id) =>
              state.update({ community_id: id, house_id: undefined, page: 1 })
            }
            onAutoSelect={() => {}}
          />
          {filters.community_id && (
            <Button
              onClick={() =>
                state.update({
                  community_id: undefined,
                  house_id: undefined,
                  page: 1,
                })
              }
            >
              全部小区
            </Button>
          )}
        </Space>
        {community.isError && (
          <ReadError
            error={community.error}
            retry={() => void community.refetch()}
          />
        )}
        <Form<SearchValues>
          key={JSON.stringify(filters)}
          layout="inline"
          initialValues={{
            ...filters,
            status: filterStatus ?? 'all',
            created_from: localTime(filters.created_from),
            created_to: localTime(filters.created_to),
          }}
          onFinish={(values) =>
            state.update({
              ...values,
              created_from: values.created_from
                ? new Date(values.created_from).toISOString()
                : undefined,
              created_to: values.created_to
                ? new Date(values.created_to).toISOString()
                : undefined,
              page: 1,
            })
          }
        >
          <Form.Item
            name="house_id"
            label={
              filters.community_id && hasPermission('property.house.read')
                ? '房屋'
                : '房屋 ID'
            }
            rules={[
              {
                pattern:
                  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
                message: '请填写有效的房屋 ID',
              },
            ]}
          >
            {filters.community_id && hasPermission('property.house.read') ? (
              <HousePicker communityId={filters.community_id} />
            ) : (
              <Input
                allowClear
                placeholder="可从房屋详情获取"
                style={{ width: 230 }}
              />
            )}
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select
              style={{ width: 140 }}
              options={[
                { value: 'all', label: '全部状态' },
                ...Object.entries(labels).map(([value, label]) => ({
                  value,
                  label,
                })),
              ]}
            />
          </Form.Item>
          {claims && (
            <Form.Item name="match_status" label="历史匹配">
              <Select
                allowClear
                style={{ width: 140 }}
                options={[
                  { value: 'matched', label: '申请时匹配' },
                  { value: 'unmatched', label: '申请时未匹配' },
                ]}
              />
            </Form.Item>
          )}
          <Form.Item
            name="created_from"
            label={claims ? '申请时间从' : '绑定时间从'}
          >
            <Input type="datetime-local" />
          </Form.Item>
          <Form.Item
            name="created_to"
            label="至"
            dependencies={['created_from']}
            rules={[
              ({ getFieldValue }) => ({
                validator: (_, value: string | undefined) =>
                  !value ||
                  !getFieldValue('created_from') ||
                  value >= String(getFieldValue('created_from'))
                    ? Promise.resolve()
                    : Promise.reject(new Error('结束时间不能早于开始时间')),
              }),
            ]}
          >
            <Input type="datetime-local" />
          </Form.Item>
          <Form.Item name="sort" label="排序">
            <Select
              style={{ width: 140 }}
              options={[
                { value: '-created_at', label: '时间从新到旧' },
                { value: 'created_at', label: '时间从旧到新' },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                查询
              </Button>
              <Button
                onClick={() =>
                  state.update({
                    status: undefined,
                    house_id: undefined,
                    community_id: undefined,
                    match_status: undefined,
                    created_from: undefined,
                    created_to: undefined,
                    sort: undefined,
                    page: 1,
                  })
                }
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      <ProTable<Claim | HouseBinding>
        rowKey="id"
        headerTitle={title}
        search={false}
        columns={columns}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 1150 }}
        options={{ reload: () => void query.refetch() }}
        locale={{
          emptyText: (
            <ListEmpty
              filtered={Object.entries(filters).some(
                ([key, value]) =>
                  !['page', 'page_size', 'sort'].includes(key) && !!value,
              )}
            />
          ),
        }}
      />
    </PageContainer>
  );
}
