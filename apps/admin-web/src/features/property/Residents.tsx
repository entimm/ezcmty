import { DatePicker } from '../../shared/DatePicker';
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  CloseOutlined,
  InfoCircleOutlined,
  SearchOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Avatar,
  Button,
  Divider,
  Empty,
  Form,
  Input,
  Radio,
  Select,
  Space,
  Spin,
  Table,
  Tag,
} from 'antd';
import type { Dayjs } from 'dayjs';
import {
  dateRangeFromInstants,
  dayStartInstant,
  dayAfterInstant,
} from '../../shared/datetime';
import { useAdmin } from '../../shared/context';
import { ApiError } from '../../shared/request';
import { DetailGrid, PageHeader, Panel, Status } from '../../shared/ui';
import { createPropertyApi, type Binding, type Claim, type Owner } from './api';
import { PropertyEditor } from './Editor';
import {
  HousingStatus,
  Metric,
  Metrics,
  QueryError,
  time,
} from './presentation';

const claimLabels = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  cancelled: '已撤回',
};
const bindingLabels = {
  active: '有效绑定',
  released: '居民已解除',
  revoked: '物业已解除',
};
type Review = { claim: Claim; decision: 'approved' | 'rejected' };

export function ClaimsPage({ detail = false }: { detail?: boolean }) {
  const { request, can, communityId, params, go } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const c = communityId || undefined;
  const page = Number(params.page) || 1;
  const size = Number(params.page_size) || 20;
  const [status, setStatus] = useState(params.status || 'pending');
  const [dates, setDates] = useState<[Dayjs, Dayjs] | null>(
    dateRangeFromInstants(params.created_from, params.created_to),
  );
  const [searchText, setSearchText] = useState('');
  const [search, setSearch] = useState('');
  const [review, setReview] = useState<Review>();
  const id = params.claim_id || params.id || '';
  const list = useQuery({
    queryKey: ['property', 'claims', c, params],
    queryFn: () =>
      api.claims({
        community_id: c,
        status:
          (params.status || 'pending') === 'all'
            ? undefined
            : params.status || 'pending',
        created_from: params.created_from,
        created_to: params.created_to,
        page,
        page_size: size,
      }),
    enabled: !detail && can('property.resident_access.read'),
  });
  const claimQuery = useQuery({
    queryKey: ['property', 'claim', id],
    queryFn: () => api.claim(id),
    enabled: detail && !!id && can('property.resident_access.read'),
  });
  const counts = useQuery({
    queryKey: ['property', 'claim-counts', c],
    queryFn: async () => {
      const [pending, matched, unmatched] = await Promise.all([
        api.claims({
          community_id: c,
          status: 'pending',
          page: 1,
          page_size: 1,
        }),
        api.claims({
          community_id: c,
          status: 'pending',
          match_status: 'matched',
          page: 1,
          page_size: 1,
        }),
        api.claims({
          community_id: c,
          status: 'pending',
          match_status: 'unmatched',
          page: 1,
          page_size: 1,
        }),
      ]);
      return {
        pending: pending.total,
        matched: matched.total,
        unmatched: unmatched.total,
      };
    },
    enabled: !detail && can('property.resident_access.read'),
  });
  const claim = claimQuery.data;
  const visible = (list.data?.items ?? []).filter(
    (row) =>
      !search ||
      `${row.applicant_name}${row.applicant_phone}${row.house_label_snapshot}`.includes(
        search,
      ),
  );
  const open = (row: Claim) =>
    go('claim-detail', { claim_id: row.id, community_id: row.community_id });
  const query = () => {
    setSearch(searchText.trim());
    go('claims', {
      ...params,
      page: '1',
      status,
      created_from: dates?.[0] ? dayStartInstant(dates[0]) : undefined,
      created_to: dates?.[1] ? dayAfterInstant(dates[1]) : undefined,
    });
  };
  return (
    <div className="property-pages">
      {detail ? (
        <>
          <PageHeader
            title="认领申请详情"
            description={
              claim?.house_label_snapshot ||
              '核验居民身份，安全授予房屋使用权限。'
            }
            back={() => go('claims')}
            extra={
              claim && (
                <>
                  <Status>{claimLabels[claim.status]}</Status>
                  {can('property.resident_access.review') &&
                    claim.status === 'pending' && (
                      <>
                        <Button
                          danger
                          icon={<CloseOutlined />}
                          onClick={() =>
                            setReview({ claim, decision: 'rejected' })
                          }
                        >
                          驳回申请
                        </Button>
                        <Button
                          type="primary"
                          icon={<CheckOutlined />}
                          onClick={() =>
                            setReview({ claim, decision: 'approved' })
                          }
                        >
                          通过申请
                        </Button>
                      </>
                    )}
                </>
              )
            }
          />
          <QueryError error={claimQuery.error} retry={claimQuery.refetch} />
          {claimQuery.isPending && <Spin />}
          {claim && <ClaimDetail claim={claim} />}
        </>
      ) : (
        <>
          <PageHeader
            title="房屋认领审核"
            description="核验居民身份，安全授予房屋使用权限。"
            extra={<Tag color="blue">物业业务 · 本公司范围</Tag>}
          />
          <Metrics>
            <Metric
              label="待审核"
              value={counts.data?.pending ?? '—'}
              sub="建议当天处理，减少居民等待"
              color="#ca812a"
            />
            <Metric
              label="资料已匹配"
              value={counts.data?.matched ?? '—'}
              sub="与业主登记姓名及手机号一致"
            />
            <Metric
              label="需人工核实"
              value={counts.data?.unmatched ?? '—'}
              sub="核实后仍可独立审批"
            />
          </Metrics>
          <Panel title="认领申请">
            <QueryError
              error={list.error || counts.error}
              retry={() => {
                void list.refetch();
                void counts.refetch();
              }}
            />
            <div
              className="filter-bar"
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 12,
                alignItems: 'center',
              }}
            >
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="本页搜索姓名、房屋、手机号"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                onPressEnter={query}
                style={{ width: 260 }}
              />
              <Select
                value={status}
                onChange={setStatus}
                style={{ width: 140 }}
                options={[
                  ...Object.entries(claimLabels).map(([value, label]) => ({
                    value,
                    label,
                  })),
                  { value: 'all', label: '全部状态' },
                ]}
              />
              <DatePicker.RangePicker
                value={dates}
                onChange={(value) => setDates(value as [Dayjs, Dayjs] | null)}
                placeholder={['申请开始日期', '申请结束日期']}
                style={{ width: 265 }}
              />
              <Space style={{ marginLeft: 'auto' }}>
                <Button type="primary" onClick={query}>
                  查询
                </Button>
                <Button
                  onClick={() => {
                    setSearchText('');
                    setSearch('');
                    setStatus('pending');
                    setDates(null);
                    go('claims');
                  }}
                >
                  重置
                </Button>
              </Space>
            </div>
            <Table<Claim>
              rowKey="id"
              size="middle"
              style={{ marginTop: 20 }}
              dataSource={visible}
              loading={list.isPending}
              pagination={{
                current: page,
                pageSize: size,
                total: list.data?.total,
                showSizeChanger: true,
                showTotal: (total) =>
                  `共 ${total} 条${search ? ' · 关键词仅筛选当前页' : ''}`,
                onChange: (next, nextSize) =>
                  go('claims', {
                    ...params,
                    page: String(next),
                    page_size: String(nextSize),
                  }),
              }}
              scroll={{ x: 880 }}
              columns={[
                {
                  title: '申请人',
                  width: 185,
                  render: (_, row) => (
                    <Space>
                      <Avatar
                        icon={<UserOutlined />}
                        style={{ background: '#eef2ff', color: '#5d72b2' }}
                      />
                      <div>
                        <strong>{row.applicant_name}</strong>
                        <div
                          className="muted"
                          style={{ fontSize: 12, marginTop: 3 }}
                        >
                          {row.applicant_phone}
                        </div>
                      </div>
                    </Space>
                  ),
                },
                {
                  title: '申请房屋',
                  width: 250,
                  render: (_, row) => (
                    <a onClick={() => open(row)}>{row.house_label_snapshot}</a>
                  ),
                },
                {
                  title: '档案匹配',
                  width: 140,
                  render: (_, row) => (
                    <Tag
                      color={
                        row.match_status === 'matched' ? 'green' : 'orange'
                      }
                    >
                      {row.match_status === 'matched'
                        ? '申请时已匹配'
                        : '需人工核实'}
                    </Tag>
                  ),
                },
                {
                  title: '申请时间',
                  dataIndex: 'created_at',
                  render: time,
                  width: 160,
                },
                {
                  title: '状态',
                  width: 100,
                  render: (_, row) => (
                    <Status>{claimLabels[row.status]}</Status>
                  ),
                },
                {
                  title: '操作',
                  width: 155,
                  fixed: 'right',
                  render: (_, row) => (
                    <Space size={2}>
                      <Button
                        type="link"
                        size="small"
                        onClick={() => open(row)}
                      >
                        详情
                      </Button>
                      {row.status === 'pending' &&
                        can('property.resident_access.review') && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() =>
                              setReview({ claim: row, decision: 'approved' })
                            }
                          >
                            快速审核
                          </Button>
                        )}
                    </Space>
                  ),
                },
              ]}
              locale={{
                emptyText: <Empty description="暂无符合条件的认领申请" />,
              }}
            />
          </Panel>
        </>
      )}
      {review && (
        <ResidentEditor
          key={review.claim.id}
          review={review}
          close={() => setReview(undefined)}
        />
      )}
    </div>
  );
}

function ClaimDetail({ claim }: { claim: Claim }) {
  const { request, can, go } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const [ownerPage, setOwnerPage] = useState(1);
  const owners = useQuery({
    queryKey: [
      'property',
      'claim-owners',
      claim.community_id,
      claim.house_id,
      ownerPage,
    ],
    queryFn: () =>
      api.owners(claim.community_id, claim.house_id, {
        page: ownerPage,
        page_size: 20,
      }),
    enabled: can('property.housing.read'),
  });
  return (
    <>
      {claim.match_status !== 'matched' && claim.status === 'pending' && (
        <Alert
          showIcon
          type="warning"
          title="申请资料与业主档案未完全匹配，请人工核实"
          description="核实业主身份后可批准申请。审批不会自动修改业主档案。"
          style={{ marginBottom: 22 }}
        />
      )}
      <div
        className="claim-detail-layout"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) 340px',
          gap: 20,
        }}
      >
        <div>
          <Panel title="申请资料">
            <DetailGrid
              items={[
                ['申请人', claim.applicant_name],
                ['联系电话', claim.applicant_phone],
                ['申请房屋', claim.house_label_snapshot],
                ['申请时间', time(claim.created_at)],
                [
                  '档案匹配',
                  <Tag
                    key="match"
                    color={
                      claim.match_status === 'matched' ? 'green' : 'orange'
                    }
                  >
                    {claim.match_status === 'matched'
                      ? '申请时已匹配'
                      : '申请时未匹配'}
                  </Tag>,
                ],
                ['居民备注', claim.applicant_remark || '未填写'],
                [
                  '审核时间',
                  claim.reviewed_at ? time(claim.reviewed_at) : '尚未审核',
                ],
                ['审核说明', claim.review_reason || '尚未填写'],
              ]}
            />
          </Panel>
          <div style={{ height: 20 }} />
          {can('property.housing.read') && (
            <Panel
              title="现有业主档案"
              extra={
                can('property.housing.read') && (
                  <Button
                    type="link"
                    size="small"
                    onClick={() =>
                      go('house-detail', {
                        community_id: claim.community_id,
                        house_id: claim.house_id,
                      })
                    }
                  >
                    完整房屋档案 <ArrowRightOutlined />
                  </Button>
                )
              }
            >
              <QueryError error={owners.error} retry={owners.refetch} />
              <Table<Owner>
                rowKey="id"
                size="middle"
                dataSource={owners.data?.items}
                loading={owners.isPending}
                pagination={{
                  current: ownerPage,
                  pageSize: 20,
                  total: owners.data?.total,
                  onChange: setOwnerPage,
                }}
                columns={[
                  { title: '业主姓名', dataIndex: 'name' },
                  { title: '联系电话', dataIndex: 'phone' },
                  {
                    title: '登记状态',
                    render: (_, row) => <HousingStatus record={row} />,
                  },
                ]}
              />
            </Panel>
          )}
        </div>
        <Panel title="审批提示">
          <div style={{ color: '#68758a', fontSize: 13, lineHeight: 1.95 }}>
            <div style={{ display: 'flex', gap: 10, marginBottom: 18 }}>
              <CheckCircleOutlined style={{ color: '#4f6bdd', marginTop: 6 }} />
              <span>
                通过后立即授予此房屋的使用权限，居民可查看账单并缴费。
              </span>
            </div>
            <div style={{ display: 'flex', gap: 10, marginBottom: 18 }}>
              <InfoCircleOutlined style={{ color: '#c58c34', marginTop: 6 }} />
              <span>未匹配申请需填写核实说明；驳回原因会向居民展示。</span>
            </div>
            <Divider />
            <div>
              身份核验请通过公司规定渠道完成。审批不会自动变更业主登记。
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}

export function BindingsPage({ detail = false }: { detail?: boolean }) {
  const { request, can, communityId, params, go } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const c = communityId || undefined;
  const id = params.binding_id || params.id || '';
  const page = Number(params.page) || 1;
  const size = Number(params.page_size) || 20;
  const [status, setStatus] = useState(params.status || 'active');
  const [dates, setDates] = useState<[Dayjs, Dayjs] | null>(
    dateRangeFromInstants(params.created_from, params.created_to),
  );
  const [searchText, setSearchText] = useState('');
  const [search, setSearch] = useState('');
  const [revoking, setRevoking] = useState<Binding>();
  const list = useQuery({
    queryKey: ['property', 'bindings', c, params],
    queryFn: () =>
      api.bindings({
        community_id: c,
        status:
          (params.status || 'active') === 'all'
            ? undefined
            : params.status || 'active',
        created_from: params.created_from,
        created_to: params.created_to,
        page,
        page_size: size,
      }),
    enabled: !detail && can('property.resident_access.read'),
  });
  const bindingQuery = useQuery({
    queryKey: ['property', 'binding', id],
    queryFn: () => api.binding(id),
    enabled: detail && !!id && can('property.resident_access.read'),
  });
  const counts = useQuery({
    queryKey: ['property', 'binding-counts', c],
    queryFn: async () => {
      const [active, released, revoked] = await Promise.all([
        api.bindings({
          community_id: c,
          status: 'active',
          page: 1,
          page_size: 1,
        }),
        api.bindings({
          community_id: c,
          status: 'released',
          page: 1,
          page_size: 1,
        }),
        api.bindings({
          community_id: c,
          status: 'revoked',
          page: 1,
          page_size: 1,
        }),
      ]);
      return { active: active.total, ended: released.total + revoked.total };
    },
    enabled: !detail && can('property.resident_access.read'),
  });
  const binding = bindingQuery.data;
  const visible = (list.data?.items ?? []).filter(
    (row) =>
      !search ||
      `${row.applicant_name}${row.applicant_phone}${row.house_label_snapshot}`.includes(
        search,
      ),
  );
  const open = (row: Binding) =>
    go('binding-detail', {
      binding_id: row.id,
      community_id: row.community_id,
    });
  const query = () => {
    setSearch(searchText.trim());
    go('bindings', {
      ...params,
      page: '1',
      status,
      created_from: dates?.[0] ? dayStartInstant(dates[0]) : undefined,
      created_to: dates?.[1] ? dayAfterInstant(dates[1]) : undefined,
    });
  };
  return (
    <div className="property-pages">
      {detail ? (
        <>
          <PageHeader
            title="居民房屋绑定详情"
            description={binding?.house_label_snapshot}
            back={() => go('bindings')}
            extra={
              binding && (
                <>
                  <Status>{bindingLabels[binding.status]}</Status>
                  {can('property.resident_access.revoke') &&
                    binding.status === 'active' && (
                      <Button danger onClick={() => setRevoking(binding)}>
                        解除房屋绑定
                      </Button>
                    )}
                </>
              )
            }
          />
          <QueryError error={bindingQuery.error} retry={bindingQuery.refetch} />
          {bindingQuery.isPending && <Spin />}
          {binding && (
            <>
              {binding.status === 'active' && !binding.effective_enabled && (
                <Alert
                  showIcon
                  type="warning"
                  title="绑定记录仍然有效，当前房屋已停用，居民暂不可使用。"
                  style={{ marginBottom: 20 }}
                />
              )}
              <Panel title="授权记录">
                <DetailGrid
                  items={[
                    ['居民姓名', binding.applicant_name],
                    ['联系电话', binding.applicant_phone],
                    ['绑定房屋', binding.house_label_snapshot],
                    ['授予时间', time(binding.granted_at)],
                    [
                      '当前使用权限',
                      binding.effective_enabled ? '可使用' : '不可使用',
                    ],
                    ['结束时间', time(binding.ended_at)],
                    ['结束原因', binding.end_reason || '—'],
                    [
                      '来源',
                      can('property.resident_access.read') ? (
                        <a
                          key="claim"
                          onClick={() =>
                            go('claim-detail', {
                              claim_id: binding.claim_application_id,
                              community_id: binding.community_id,
                            })
                          }
                        >
                          查看原认领申请 <ArrowRightOutlined />
                        </a>
                      ) : (
                        '认领审核记录'
                      ),
                    ],
                  ]}
                />
                <Divider />
                <Space>
                  {can('property.housing.read') && (
                    <Button
                      onClick={() =>
                        go('house-detail', {
                          community_id: binding.community_id,
                          house_id: binding.house_id,
                        })
                      }
                    >
                      查看房屋档案
                    </Button>
                  )}
                  <Button onClick={() => go('bindings')}>返回绑定列表</Button>
                </Space>
              </Panel>
            </>
          )}
        </>
      ) : (
        <>
          <PageHeader
            title="居民房屋绑定"
            description="查看居民的房屋使用权限，保留完整授权与解除记录。"
          />
          <Metrics>
            <Metric
              label="当前有效绑定"
              value={counts.data?.active ?? '—'}
              sub="人工审核通过后授予权限"
            />
            <Metric
              label="本页暂不可使用"
              value={
                list.isSuccess
                  ? list.data.items.filter(
                      (row) =>
                        row.status === 'active' && !row.effective_enabled,
                    ).length
                  : '—'
              }
              sub="房屋或上级已停用"
              color="#ca812a"
            />
            <Metric
              label="已解除"
              value={counts.data?.ended ?? '—'}
              sub="历史记录完整保留"
            />
          </Metrics>
          <Panel title="绑定记录">
            <QueryError
              error={list.error || counts.error}
              retry={() => {
                void list.refetch();
                void counts.refetch();
              }}
            />
            <div
              className="filter-bar"
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 12,
                alignItems: 'center',
              }}
            >
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="本页搜索居民姓名、房屋位置"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                onPressEnter={query}
                style={{ width: 260 }}
              />
              <Select
                value={status}
                onChange={setStatus}
                style={{ width: 140 }}
                options={[
                  ...Object.entries(bindingLabels).map(([value, label]) => ({
                    value,
                    label,
                  })),
                  { value: 'all', label: '全部状态' },
                ]}
              />
              <DatePicker.RangePicker
                value={dates}
                onChange={(value) => setDates(value as [Dayjs, Dayjs] | null)}
                placeholder={['登记开始日期', '登记结束日期']}
                style={{ width: 265 }}
              />
              <Space style={{ marginLeft: 'auto' }}>
                <Button type="primary" onClick={query}>
                  查询
                </Button>
                <Button
                  onClick={() => {
                    setSearchText('');
                    setSearch('');
                    setStatus('active');
                    setDates(null);
                    go('bindings');
                  }}
                >
                  重置
                </Button>
              </Space>
            </div>
            <Table<Binding>
              size="middle"
              rowKey="id"
              dataSource={visible}
              loading={list.isPending}
              style={{ marginTop: 20 }}
              pagination={{
                current: page,
                pageSize: size,
                total: list.data?.total,
                showSizeChanger: true,
                showTotal: (total) =>
                  `共 ${total} 条${search ? ' · 关键词仅筛选当前页' : ''}`,
                onChange: (next, nextSize) =>
                  go('bindings', {
                    ...params,
                    page: String(next),
                    page_size: String(nextSize),
                  }),
              }}
              scroll={{ x: 880 }}
              columns={[
                {
                  title: '居民',
                  width: 170,
                  render: (_, row) => (
                    <div>
                      <strong>{row.applicant_name}</strong>
                      <div
                        className="muted"
                        style={{ fontSize: 12, marginTop: 4 }}
                      >
                        {row.applicant_phone}
                      </div>
                    </div>
                  ),
                },
                {
                  title: '绑定房屋',
                  width: 260,
                  render: (_, row) => (
                    <a onClick={() => open(row)}>{row.house_label_snapshot}</a>
                  ),
                },
                {
                  title: '授权状态',
                  width: 125,
                  render: (_, row) => (
                    <Status>{bindingLabels[row.status]}</Status>
                  ),
                },
                {
                  title: '当前使用权限',
                  width: 125,
                  render: (_, row) => (
                    <Tag color={row.effective_enabled ? 'green' : undefined}>
                      {row.effective_enabled ? '可使用' : '不可使用'}
                    </Tag>
                  ),
                },
                {
                  title: '授予时间',
                  dataIndex: 'granted_at',
                  render: time,
                  width: 160,
                },
                {
                  title: '操作',
                  width: 130,
                  fixed: 'right',
                  render: (_, row) => (
                    <Space>
                      <Button
                        type="link"
                        size="small"
                        onClick={() => open(row)}
                      >
                        详情
                      </Button>
                      {can('property.resident_access.revoke') &&
                        row.status === 'active' && (
                          <Button
                            type="link"
                            danger
                            size="small"
                            onClick={() => setRevoking(row)}
                          >
                            解除
                          </Button>
                        )}
                    </Space>
                  ),
                },
              ]}
              locale={{
                emptyText: <Empty description="暂无符合条件的绑定记录" />,
              }}
            />
          </Panel>
        </>
      )}
      {revoking && (
        <ResidentEditor
          key={revoking.id}
          binding={revoking}
          close={() => setRevoking(undefined)}
        />
      )}
    </div>
  );
}

function ResidentEditor({
  review,
  binding,
  close,
}: {
  review?: Review;
  binding?: Binding;
  close: () => void;
}) {
  const { request, can } = useAdmin();
  const { message } = App.useApp();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const cache = useQueryClient();
  const [form] = Form.useForm();
  const decision = Form.useWatch('decision', form) as string | undefined;
  const rejected = !!review && (decision || review.decision) === 'rejected';
  const needsReason =
    !!binding || rejected || review?.claim.match_status !== 'matched';
  const claim = review?.claim;
  const record = claim || binding;
  const reasonLabel = binding
    ? '解除原因'
    : rejected
      ? '驳回原因'
      : needsReason
        ? '核实说明'
        : '审核说明（选填）';
  const submit = async (values: Record<string, unknown>) => {
    try {
      if (review) {
        if (!can('property.resident_access.review'))
          throw new Error('没有审核权限');
        await api.reviewClaim(review.claim.id, {
          expected_row_version: review.claim.row_version,
          decision: values.decision,
          ...(typeof values.reason === 'string' && values.reason.trim()
            ? { reason: values.reason.trim() }
            : {}),
        });
      } else if (binding) {
        if (!can('property.resident_access.revoke'))
          throw new Error('没有解除权限');
        await api.revokeBinding(binding.id, {
          expected_row_version: binding.row_version,
          reason: String(values.reason).trim(),
        });
      }
    } catch (failure) {
      await cache.invalidateQueries({ queryKey: ['property'] });
      if (!(failure instanceof ApiError) || failure.status >= 500)
        throw new Error(
          '操作结果尚未确定，请关闭后重新读取记录核实，避免重复办理。',
          { cause: failure },
        );
      throw failure;
    }
    await cache.invalidateQueries({ queryKey: ['property'] });
    message.success(
      binding
        ? '绑定已解除'
        : values.decision === 'approved'
          ? '申请已通过，已授予房屋使用权限'
          : '申请已驳回',
    );
  };
  return (
    <PropertyEditor
      title={
        binding
          ? '解除居民房屋绑定'
          : rejected
            ? '驳回认领申请'
            : '审核认领申请'
      }
      form={form}
      initial={review ? { decision: review.decision } : {}}
      submit={submit}
      close={close}
      danger={!!binding || rejected}
      confirmLabel={binding ? '确认解除' : rejected ? '确认驳回' : '确认通过'}
    >
      <Alert
        showIcon
        type={binding || rejected ? 'warning' : 'info'}
        title={
          binding
            ? '解除后，居民将失去此房屋的使用权限'
            : rejected
              ? '驳回原因将向居民展示'
              : '通过后立即授予房屋使用权限'
        }
        description={
          binding
            ? '已有账单与收款记录不受影响。再次认领需重新提交申请并审批。'
            : rejected
              ? '请清楚说明需补充或更正的内容，便于居民重新申请。'
              : claim?.match_status === 'matched'
                ? '申请资料与业主档案匹配。请确认已核实业主身份。'
                : '申请资料与业主档案未匹配，请完成核实并填写过程。此操作不会自动修改业主档案。'
        }
        style={{ marginBottom: 20 }}
      />
      <div
        style={{
          padding: 16,
          background: '#f6f8fc',
          borderRadius: 8,
          marginBottom: 20,
        }}
      >
        <strong>{record?.applicant_name}</strong>
        <span className="muted">{record?.applicant_phone}</span>
        <div style={{ marginTop: 8 }}>{record?.house_label_snapshot}</div>
      </div>
      {review && (
        <Form.Item
          name="decision"
          label="审核结果"
          rules={[{ required: true }]}
        >
          <Radio.Group
            options={[
              { value: 'approved', label: '通过申请' },
              { value: 'rejected', label: '驳回申请' },
            ]}
          />
        </Form.Item>
      )}
      <Form.Item
        name="reason"
        label={reasonLabel}
        rules={[
          {
            required: needsReason,
            whitespace: true,
            message: `请填写${reasonLabel}`,
          },
          { max: 1000 },
        ]}
      >
        <Input.TextArea
          rows={3}
          maxLength={1000}
          showCount
          placeholder="请填写核实过程或处理原因，便于后续追溯"
        />
      </Form.Item>
    </PropertyEditor>
  );
}
