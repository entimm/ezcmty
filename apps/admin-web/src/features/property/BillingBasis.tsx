import { DatePicker } from '../../shared/DatePicker';
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { PlusOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Col,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
} from 'antd';
import type { Dayjs } from 'dayjs';
import { useAdmin } from '../../shared/context';
import { businessNow } from '../../shared/datetime';
import { DetailGrid, Panel } from '../../shared/ui';
import {
  createPropertyApi,
  type FeeBasis,
  type HouseOption,
  type Usage,
} from './api';
import { PropertyEditor } from './Editor';
import {
  basisText,
  cents,
  QueryError,
  time,
  toCents,
  usageLabels,
} from './presentation';

type BasisHouse = {
  id: string;
  community_id: string;
  display_address: string;
  effective_enabled: boolean;
};

export function BillingBasisDialog({ onClose }: { onClose: () => void }) {
  const { request, can, communityId, confirmLeave } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const [room, setRoom] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<HouseOption>();
  const houses = useQuery({
    queryKey: ['property', 'basis-house-options', communityId, room, page],
    queryFn: () =>
      api.houseOptions(communityId, {
        room_no: room || undefined,
        page,
        page_size: 20,
      }),
    enabled: !!communityId && can('property.bill.read'),
  });
  const choose = (house: HouseOption) => confirmLeave(() => setSelected(house));
  return (
    <Drawer
      open
      title="计费依据与试算"
      size={880}
      onClose={() => confirmLeave(onClose)}
    >
      <Alert
        type="info"
        showIcon
        title="选择房屋查询计费依据和试算；新增依据版本仅影响后续建账。"
        style={{ marginBottom: 18 }}
      />
      <Input.Search
        aria-label="查询计费依据的房号"
        placeholder="按完整房号查询"
        allowClear
        onSearch={(value) => {
          setRoom(value.trim());
          setPage(1);
        }}
        style={{ marginBottom: 16 }}
      />
      <QueryError error={houses.error} retry={houses.refetch} />
      <Table<HouseOption>
        rowKey="id"
        size="small"
        loading={houses.isPending}
        dataSource={houses.data?.items}
        pagination={{
          current: page,
          pageSize: 20,
          total: houses.data?.total,
          onChange: setPage,
        }}
        columns={[
          { title: '房屋位置', dataIndex: 'label' },
          {
            title: '状态',
            render: (_, house) => (house.effective_enabled ? '可用' : '已停用'),
          },
          {
            title: '操作',
            render: (_, house) => (
              <Button type="link" onClick={() => choose(house)}>
                {selected?.id === house.id ? '当前房屋' : '查看依据'}
              </Button>
            ),
          },
        ]}
      />
      {selected ? (
        <div style={{ marginTop: 20 }}>
          <strong>{selected.label}</strong>
          <div style={{ marginTop: 14 }}>
            <FeeBasisPanel
              key={selected.id}
              house={{ ...selected, display_address: selected.label }}
            />
          </div>
        </div>
      ) : (
        <Empty description="请选择房屋查看计费依据" />
      )}
    </Drawer>
  );
}

export function FeeBasisPanel({ house }: { house: BasisHouse }) {
  const { request, can } = useAdmin();
  const { message } = App.useApp();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const queryClient = useQueryClient();
  const [month, setMonth] = useState<Dayjs>(businessNow());
  const [page, setPage] = useState(1);
  const [preparing, setPreparing] = useState(false);
  const [editing, setEditing] = useState<{
    source?: FeeBasis;
    expected: number;
  }>();
  const [detail, setDetail] = useState<FeeBasis>();
  const bases = useQuery({
    queryKey: ['property', 'bases', house.community_id, house.id, page],
    queryFn: () =>
      api.bases(house.community_id, house.id, { page, page_size: 20 }),
    enabled: can('property.bill.read'),
  });
  const calculation = useQuery({
    queryKey: [
      'property',
      'calculation',
      house.community_id,
      house.id,
      month.format('YYYY-MM'),
    ],
    queryFn: () =>
      api.calculate(house.community_id, house.id, month.format('YYYY-MM')),
    enabled: can('property.bill.read'),
    retry: false,
  });
  const begin = async (source?: FeeBasis) => {
    if (preparing) return;
    setPreparing(true);
    try {
      const latest = await api.bases(house.community_id, house.id, {
        page: 1,
        page_size: 1,
      });
      setEditing({
        source: source || latest.items[0],
        expected: latest.items[0]?.version_no ?? 0,
      });
    } catch (error) {
      void message.error(
        error instanceof Error ? error.message : '计费依据读取失败，请重试',
      );
    } finally {
      setPreparing(false);
    }
  };
  if (!can('property.bill.read'))
    return <Empty description="没有计费依据查看权限" />;
  return (
    <>
      <Panel
        title="当月计费试算"
        extra={
          <DatePicker
            picker="month"
            allowClear={false}
            value={month}
            onChange={(value) => value && setMonth(value)}
          />
        }
      >
        <QueryError error={calculation.error} retry={calculation.refetch} />
        <Spin spinning={calculation.isPending}>
          <DetailGrid
            items={[
              [
                '适用依据',
                calculation.data?.basis
                  ? `v${calculation.data.basis.version_no} · ${calculation.data.basis.effective_from_month} 起生效`
                  : '暂无适用依据',
              ],
              ['计费方式', basisText(calculation.data?.basis)],
              [
                '建筑面积',
                calculation.data?.basis?.area_sqm
                  ? `${calculation.data.basis.area_sqm} ㎡`
                  : '未设置',
              ],
              [
                '本月应收',
                calculation.data?.available
                  ? cents(calculation.data.receivable_cents)
                  : '请先新增计费依据',
              ],
            ]}
          />
        </Spin>
      </Panel>
      <div style={{ height: 18 }} />
      <Panel
        title="计费依据版本"
        extra={
          can('property.fee_basis.manage') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              loading={preparing}
              disabled={!house.effective_enabled}
              onClick={() => void begin()}
            >
              新增依据版本
            </Button>
          )
        }
      >
        <Alert
          type="info"
          showIcon
          title="版本保存后不可修改。新增版本仅影响后续试算，已经创建的账单继续使用原依据。"
          style={{ marginBottom: 18 }}
        />
        <QueryError error={bases.error} retry={bases.refetch} />
        <Table<FeeBasis>
          rowKey="id"
          size="middle"
          dataSource={bases.data?.items}
          loading={bases.isPending}
          pagination={{
            current: page,
            pageSize: 20,
            total: bases.data?.total,
            onChange: setPage,
          }}
          columns={[
            {
              title: '版本',
              render: (_, basis) => <Tag color="blue">v{basis.version_no}</Tag>,
            },
            { title: '生效月份', dataIndex: 'effective_from_month' },
            { title: '计费标准', render: (_, basis) => basisText(basis) },
            { title: '变更原因', dataIndex: 'change_reason' },
            {
              title: '操作',
              render: (_, basis) => (
                <Space>
                  <Button
                    type="link"
                    size="small"
                    onClick={() => setDetail(basis)}
                  >
                    详情
                  </Button>
                  {can('property.fee_basis.manage') && (
                    <Button
                      type="link"
                      size="small"
                      disabled={!house.effective_enabled || preparing}
                      onClick={() => void begin(basis)}
                    >
                      复制为新版本
                    </Button>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Panel>
      {editing && (
        <BasisEditor
          house={house}
          source={editing.source}
          expected={editing.expected}
          close={() => setEditing(undefined)}
          done={async () => {
            await queryClient.invalidateQueries({ queryKey: ['property'] });
          }}
        />
      )}
      {detail && (
        <BasisDetail basis={detail} close={() => setDetail(undefined)} />
      )}
    </>
  );
}

function BasisDetail({ basis, close }: { basis: FeeBasis; close: () => void }) {
  const [form] = Form.useForm();
  return (
    <PropertyEditor
      title={`计费依据 v${basis.version_no}`}
      form={form}
      close={close}
      readOnly
    >
      <DetailGrid
        items={[
          ['依据版本', `v${basis.version_no}`],
          ['生效月份', basis.effective_from_month],
          ['房屋用途', usageLabels[basis.house_usage]],
          ['计费标准', basisText(basis)],
          ['变更原因', basis.change_reason],
          ['创建时间', time(basis.created_at)],
        ]}
      />
    </PropertyEditor>
  );
}

function BasisEditor({
  house,
  source,
  expected,
  close,
  done,
}: {
  house: BasisHouse;
  source?: FeeBasis;
  expected: number;
  close: () => void;
  done: () => Promise<void>;
}) {
  const { request, can } = useAdmin();
  const { message } = App.useApp();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const [form] = Form.useForm();
  const method = Form.useWatch('method', form);
  const [expectedLatest, setExpectedLatest] = useState(expected);
  const [changedBasis, setChangedBasis] = useState<FeeBasis>();
  const initial = {
    month: businessNow().add(1, 'month'),
    house_usage: source?.house_usage ?? 'residential',
    method: source?.fixed_amount_cents != null ? 'fixed' : 'area',
    area: source?.area_sqm ? Number(source.area_sqm) : undefined,
    rate:
      source?.unit_price_cents != null
        ? source.unit_price_cents / 100
        : undefined,
    fixed:
      source?.fixed_amount_cents != null
        ? source.fixed_amount_cents / 100
        : undefined,
  };
  return (
    <PropertyEditor
      title="新增计费依据版本"
      form={form}
      initial={initial}
      close={close}
      extra={
        changedBasis && (
          <Alert
            type="warning"
            showIcon
            title={`当前已有依据 v${changedBasis.version_no}`}
            description={`${changedBasis.effective_from_month} 起生效，${basisText(changedBasis)}。请核对后再保存，当前填写内容已保留。`}
            style={{ marginBottom: 16 }}
          />
        )
      }
      submit={async (values) => {
        if (!can('property.fee_basis.manage'))
          throw new Error('没有计费依据维护权限');
        const latest = await api.bases(house.community_id, house.id, {
          page: 1,
          page_size: 1,
        });
        const version = latest.items[0]?.version_no ?? 0;
        if (version !== expectedLatest) {
          setExpectedLatest(version);
          setChangedBasis(latest.items[0]);
          throw new Error('计费依据已有新版本，请核对后重新保存');
        }
        await api.createBasis(house.community_id, house.id, {
          expected_latest_version_no: expectedLatest,
          effective_from_month: (values.month as Dayjs).format('YYYY-MM'),
          house_usage: values.house_usage as Usage,
          area_sqm: values.method === 'area' ? String(values.area) : null,
          unit_price_cents:
            values.method === 'area' ? toCents(values.rate) : null,
          fixed_amount_cents:
            values.method === 'fixed' ? toCents(values.fixed) : null,
          change_reason: String(values.reason).trim(),
        });
        await done();
        void message.success('新的计费依据版本已保存');
      }}
    >
      <Alert
        type="info"
        showIcon
        title="新版本保存后不可修改，已建账单不受影响。"
        description={house.display_address}
        style={{ marginBottom: 20 }}
      />
      <Form.Item name="month" label="生效月份" rules={[{ required: true }]}>
        <DatePicker picker="month" style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item
        name="house_usage"
        label="房屋用途"
        rules={[{ required: true }]}
      >
        <Select
          options={Object.entries(usageLabels).map(([value, label]) => ({
            value,
            label,
          }))}
        />
      </Form.Item>
      <Form.Item name="method" label="计费方式">
        <Radio.Group
          options={[
            { value: 'area', label: '面积 × 单价' },
            { value: 'fixed', label: '固定月费' },
          ]}
        />
      </Form.Item>
      {method === 'fixed' ? (
        <Form.Item
          name="fixed"
          label="固定月费（元）"
          rules={[{ required: true }]}
        >
          <InputNumber min={0} precision={2} style={{ width: '100%' }} />
        </Form.Item>
      ) : (
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="area"
              label="建筑面积（㎡）"
              rules={[{ required: true }]}
            >
              <InputNumber
                min={0}
                max={99999999}
                precision={4}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="rate"
              label="月单价（元 / ㎡）"
              rules={[{ required: true }]}
            >
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
      )}
      <Form.Item
        name="reason"
        label="变更原因"
        rules={[{ required: true, whitespace: true, max: 500 }]}
      >
        <Input.TextArea rows={3} maxLength={500} showCount />
      </Form.Item>
    </PropertyEditor>
  );
}
