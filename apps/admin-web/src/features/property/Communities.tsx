import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BankOutlined, SearchOutlined } from '@ant-design/icons';
import {
  Alert,
  Avatar,
  Button,
  Form,
  Input,
  Select,
  Space,
  Spin,
  Table,
  Tag,
} from 'antd';
import { useAdmin } from '../../shared/context';
import { DetailGrid, PageHeader, Panel, Status } from '../../shared/ui';
import { createPropertyApi, type Community } from './api';
import { PropertyEditor } from './Editor';
import { Metric, Metrics, QueryError, time } from './presentation';

export function CommunitiesPage() {
  const { request, can, params, go } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const [search, setSearch] = useState(params.name || params.code || '');
  const [by, setBy] = useState(params.code ? 'code' : 'name');
  const [enabled, setEnabled] = useState<string | undefined>(params.enabled);
  const [selected, setSelected] = useState<string>();
  const page = Number(params.page) || 1;
  const size = Number(params.page_size) || 20;
  const list = useQuery({
    queryKey: ['property', 'community-list', params],
    queryFn: () =>
      api.communities({
        page,
        page_size: size,
        name: params.name,
        code: params.code,
        enabled:
          params.enabled === undefined ? undefined : params.enabled === 'true',
      }),
    enabled: can('property.community.read'),
  });
  const counts = useQuery({
    queryKey: ['property', 'community-counts'],
    queryFn: async () => {
      const [all, active] = await Promise.all([
        api.communities({ page: 1, page_size: 1 }),
        api.communities({ page: 1, page_size: 1, enabled: true }),
      ]);
      return { total: all.total, active: active.total };
    },
    enabled: can('property.community.read'),
  });
  const company = useQuery({
    queryKey: ['property', 'company'],
    queryFn: api.company,
    enabled: can('property.company.read'),
  });
  const searchNow = () =>
    go('communities', {
      name: undefined,
      code: undefined,
      [by]: search.trim() || undefined,
      enabled,
      page: '1',
    });
  return (
    <div className="property-pages">
      <PageHeader
        title="小区资料"
        description="本公司全部小区的基础资料。公司与小区接入信息由平台维护。"
        extra={<Tag>公司范围 · 不随当前小区切换</Tag>}
      />
      <Metrics>
        <Metric
          label="管理小区"
          value={counts.data?.total ?? '—'}
          sub={company.data?.name || '本公司全部小区'}
        />
        <Metric
          label="已启用"
          value={counts.data?.active ?? '—'}
          sub="可开展新增业务"
          color="#237c63"
        />
        <Metric
          label="已停用"
          value={counts.data ? counts.data.total - counts.data.active : '—'}
          sub="保留资料与历史数据"
        />
      </Metrics>
      <Panel title="本公司小区">
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
            alignItems: 'center',
            gap: 12,
          }}
        >
          <Space.Compact>
            <Select
              value={by}
              onChange={setBy}
              style={{ width: 105 }}
              options={[
                { value: 'name', label: '小区名称' },
                { value: 'code', label: '小区编码' },
              ]}
            />
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="输入小区名称或编码"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onPressEnter={searchNow}
              style={{ width: 220 }}
            />
          </Space.Compact>
          <Select
            allowClear
            placeholder="全部状态"
            value={enabled}
            onChange={setEnabled}
            style={{ width: 140 }}
            options={[
              { value: 'true', label: '已启用' },
              { value: 'false', label: '已停用' },
            ]}
          />
          <Space style={{ marginLeft: 'auto' }}>
            <Button type="primary" onClick={searchNow}>
              查询
            </Button>
            <Button
              onClick={() => {
                setSearch('');
                setEnabled(undefined);
                go('communities');
              }}
            >
              重置
            </Button>
          </Space>
        </div>
        <Table<Community>
          rowKey="id"
          size="middle"
          dataSource={list.data?.items}
          loading={list.isPending}
          style={{ marginTop: 22 }}
          pagination={{
            current: page,
            pageSize: size,
            total: list.data?.total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (next, nextSize) =>
              go('communities', {
                ...params,
                page: String(next),
                page_size: String(nextSize),
              }),
          }}
          columns={[
            {
              title: '小区名称',
              render: (_, row) => (
                <Space size={12}>
                  <Avatar
                    shape="square"
                    size={40}
                    style={{ background: '#edf2ff', color: '#5871c7' }}
                    icon={<BankOutlined />}
                  />
                  <div>
                    <strong style={{ color: '#263954' }}>{row.name}</strong>
                    <div
                      className="muted"
                      style={{ fontSize: 12, marginTop: 4 }}
                    >
                      {row.code}
                    </div>
                  </div>
                </Space>
              ),
            },
            { title: '小区地址', dataIndex: 'address' },
            { title: '接入时间', dataIndex: 'created_at', render: time },
            {
              title: '状态',
              render: (_, row) => (
                <Status>{row.enabled ? '已启用' : '已停用'}</Status>
              ),
            },
            {
              title: '操作',
              render: (_, row) => (
                <Button
                  type="link"
                  size="small"
                  onClick={() => setSelected(row.id)}
                >
                  查看资料
                </Button>
              ),
            },
          ]}
        />
      </Panel>
      {selected && (
        <CommunityDetail
          key={selected}
          id={selected}
          close={() => setSelected(undefined)}
        />
      )}
    </div>
  );
}
function CommunityDetail({ id, close }: { id: string; close: () => void }) {
  const { request } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const record = useQuery({
    queryKey: ['property', 'community', id],
    queryFn: () => api.community(id),
  });
  const [form] = Form.useForm();
  const community = record.data;
  return (
    <PropertyEditor
      title="小区基础资料"
      form={form}
      close={close}
      readOnly
      width={660}
    >
      <QueryError error={record.error} retry={record.refetch} />
      <Spin spinning={record.isPending}>
        {community && (
          <>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 14,
                marginBottom: 24,
              }}
            >
              <Avatar
                size={52}
                shape="square"
                icon={<BankOutlined />}
                style={{ background: '#edf2ff', color: '#5671c2' }}
              />
              <div>
                <h3 style={{ margin: 0 }}>{community.name}</h3>
                <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>
                  {community.code} · 只读基础资料
                </div>
              </div>
              <Status>{community.enabled ? '已启用' : '已停用'}</Status>
            </div>
            <DetailGrid
              items={[
                ['所属公司', community.property_company_name],
                ['详细地址', community.address],
                ['小区编码', community.code],
                ['接入时间', time(community.created_at)],
                ['更新时间', time(community.updated_at)],
                ['资料维护', '由平台统一维护'],
              ]}
            />
            <Alert
              style={{ marginTop: 22 }}
              type="info"
              showIcon
              title="如需修改名称、地址或启停状态，请联系平台管理员。"
            />
          </>
        )}
      </Spin>
    </PropertyEditor>
  );
}

export function CompanyPage() {
  const { request } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const record = useQuery({
    queryKey: ['property', 'company'],
    queryFn: api.company,
  });
  return (
    <>
      <PageHeader
        title="公司资料"
        description="当前公司基础资料，由平台统一维护。"
        extra={<Tag>公司范围 · 只读</Tag>}
      />
      <QueryError error={record.error} retry={record.refetch} />
      <Panel title="物业公司资料">
        <Spin spinning={record.isPending}>
          {record.data && (
            <DetailGrid
              items={[
                ['公司名称', record.data.name],
                ['公司编码', record.data.code],
                ['联系人', record.data.contact_name || '未填写'],
                ['联系电话', record.data.contact_phone || '未填写'],
                ['状态', record.data.enabled ? '已启用' : '已停用'],
                ['接入时间', time(record.data.created_at)],
              ]}
            />
          )}
        </Spin>
      </Panel>
    </>
  );
}
