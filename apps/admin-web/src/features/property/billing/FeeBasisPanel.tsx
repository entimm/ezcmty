import { useState } from 'react';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Drawer, Form, Input, Select, Space } from 'antd';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';
import { useListState } from '../../../shared/hooks/use-list-state';
import { useOperation } from '../../../shared/hooks/use-operation';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import { applyFormErrors } from '../../../shared/form-utils';
import { usePropertySession } from '../hooks';
import type { House } from '../housing/api';
import type { FeeBasis, HouseUsage } from './api';
import { useBillingApi } from './hooks';
import { BasisProof, ReasonInput } from './BillParts';
import {
  businessToday,
  money,
  monthRule,
  parseMoney,
  textRule,
  usageLabels,
  validMonth,
  yuan,
} from './values';

interface BasisValues {
  effective_from_month: string;
  house_usage: HouseUsage;
  area_sqm?: string;
  rate?: string;
  fixed?: string;
  change_reason: string;
}
function basisAmount(
  values: Pick<BasisValues, 'area_sqm' | 'rate' | 'fixed'>,
): number {
  if (values.fixed?.trim()) return parseMoney(values.fixed);
  const area = values.area_sqm?.trim() ?? '';
  if (!/^(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?$/.test(area))
    throw new Error('请核对房屋面积');
  const [whole, fraction = ''] = area.split('.');
  const quantity = BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'));
  if (quantity <= 0n) throw new Error('房屋面积必须大于 0');
  const cents =
    (quantity * BigInt(parseMoney(values.rate ?? '')) + 5000n) / 10000n;
  if (cents > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error('金额超过支持范围');
  return Number(cents);
}
function BasisEditor({
  communityId,
  house,
  latest,
  copy,
  done,
}: {
  communityId: string;
  house: House;
  latest: number;
  copy?: FeeBasis;
  done: () => void;
}) {
  const api = useBillingApi();
  const { refreshSession } = usePropertySession();
  const client = useQueryClient();
  const [form] = Form.useForm<BasisValues>();
  const [expected, setExpected] = useState(latest);
  const [error, setError] = useState<unknown>();
  const [inputError, setInputError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const dirty = useDirtyForm();
  const operation = useOperation({
    resources: ['fee-bases', 'fee-calculations'],
    conflictResources: ['fee-bases', 'fee-calculations'],
    refreshSession,
  });
  const fixed = Form.useWatch('fixed', form) as string | undefined;
  const area = Form.useWatch('area_sqm', form) as string | undefined;
  const rate = Form.useWatch('rate', form) as string | undefined;
  const hasFixed = !!fixed?.trim();
  let amount: number | undefined;
  try {
    amount = basisAmount({ fixed, area_sqm: area, rate });
  } catch {
    /* Wait for complete inputs. */
  }
  const close = () => {
    if (!operation.isPending) dirty.close(done);
  };
  return (
    <Drawer
      open
      title={
        copy ? `复制 v${copy.version_no} 为新依据版本` : '新增计费依据版本'
      }
      size={620}
      onClose={close}
      maskClosable={false}
    >
      <OperationError error={error ?? operation.error} />
      {inputError && (
        <Alert
          type="error"
          showIcon
          title={inputError}
          style={{ marginBottom: 16 }}
        />
      )}
      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        showIcon
        title="依据版本保存后不可修改"
        description="同月新增版本替代后续试算的依据，已建账单继续引用原版本。每个版本保存完整参数。"
      />
      <p>已核对最新版本：v{expected}</p>
      <Button
        style={{ marginBottom: 16 }}
        loading={refreshing}
        disabled={operation.isPending}
        onClick={async () => {
          setRefreshing(true);
          setError(undefined);
          try {
            const result = await api.bases(communityId, house.id, {
              page: 1,
              page_size: 1,
            });
            setExpected(result.items[0]?.version_no ?? 0);
            await client.invalidateQueries({ queryKey: ['fee-bases'] });
          } catch (caught) {
            setError(caught);
          } finally {
            setRefreshing(false);
          }
        }}
      >
        刷新版本号并核对
      </Button>
      <Form<BasisValues>
        form={form}
        layout="vertical"
        autoComplete="off"
        initialValues={{
          effective_from_month:
            copy?.effective_from_month ?? businessToday().slice(0, 7),
          house_usage: copy?.house_usage ?? 'residential',
          area_sqm: copy?.area_sqm ?? undefined,
          rate:
            copy?.unit_price_cents == null
              ? undefined
              : money(copy.unit_price_cents),
          fixed:
            copy?.fixed_amount_cents == null
              ? undefined
              : money(copy.fixed_amount_cents),
        }}
        disabled={operation.isPending || refreshing}
        onValuesChange={dirty.changed}
        onFinish={async (values) => {
          setError(undefined);
          setInputError('');
          try {
            basisAmount(values);
          } catch (caught) {
            setInputError(
              caught instanceof Error ? caught.message : '请核对计费参数',
            );
            return;
          }
          try {
            await operation.mutateAsync({
              run: () =>
                api.createBasis(communityId, house.id, {
                  expected_latest_version_no: expected,
                  effective_from_month: values.effective_from_month,
                  house_usage: values.house_usage,
                  area_sqm: values.area_sqm?.trim() || null,
                  unit_price_cents: values.rate?.trim()
                    ? parseMoney(values.rate)
                    : null,
                  fixed_amount_cents: values.fixed?.trim()
                    ? parseMoney(values.fixed)
                    : null,
                  change_reason: values.change_reason.trim(),
                }),
            });
            dirty.reset();
            done();
          } catch (caught) {
            setError(caught);
            applyFormErrors(form, caught, [
              'effective_from_month',
              'house_usage',
              'area_sqm',
              'change_reason',
            ]);
          }
        }}
      >
        <Form.Item
          name="effective_from_month"
          label="生效月份"
          rules={[monthRule]}
        >
          <Input type="month" />
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
        <Form.Item
          name="fixed"
          label="固定月金额（元，可填 0，留空按面积计算）"
          rules={[
            {
              validator: async (_, value: unknown) => {
                if (typeof value === 'string' && value.trim())
                  parseMoney(value);
              },
            },
          ]}
        >
          <Input inputMode="decimal" />
        </Form.Item>
        <Form.Item
          name="area_sqm"
          label="房屋面积（㎡，最多四位小数）"
          dependencies={['fixed']}
          rules={[
            ({ getFieldValue }) => ({
              validator: async (_, value: unknown) => {
                const text = typeof value === 'string' ? value.trim() : '';
                const fixedValue = getFieldValue('fixed') as string | undefined;
                if (fixedValue?.trim() && !text) return;
                if (
                  !/^(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?$/.test(text) ||
                  /^0(?:\.0+)?$/.test(text)
                )
                  throw new Error(
                    '请输入大于 0 的面积，最多八位整数、四位小数',
                  );
              },
            }),
          ]}
        >
          <Input inputMode="decimal" />
        </Form.Item>
        <Form.Item
          name="rate"
          label="每㎡月单价（元）"
          dependencies={['fixed']}
          rules={[
            ({ getFieldValue }) => ({
              validator: async (_, value: unknown) => {
                const fixedValue = getFieldValue('fixed') as string | undefined;
                if (fixedValue?.trim() && (value == null || value === ''))
                  return;
                parseMoney(typeof value === 'string' ? value : '');
              },
            }),
          ]}
        >
          <Input inputMode="decimal" />
        </Form.Item>
        <Form.Item
          name="change_reason"
          label="变更原因"
          rules={[textRule(1000, true)]}
        >
          <ReasonInput />
        </Form.Item>
        {amount !== undefined && (
          <Alert
            style={{ marginBottom: 16 }}
            type="info"
            title={`月应收 ${yuan(amount)}${hasFixed ? '（以固定金额为准）' : '（最终舍入到分）'}`}
          />
        )}
        <Space>
          <Button
            type="primary"
            htmlType="submit"
            loading={operation.isPending}
          >
            保存新版本
          </Button>
          <Button onClick={close}>取消</Button>
        </Space>
      </Form>
    </Drawer>
  );
}
export function FeeBasisPanel({
  communityId,
  house,
}: {
  communityId: string;
  house: House;
}) {
  const api = useBillingApi();
  const { hasPermission } = usePropertySession();
  const state = useListState('basis_');
  const [month, setMonth] = useState(businessToday().slice(0, 7));
  const [editor, setEditor] = useState<{ copy?: FeeBasis }>();
  const [detail, setDetail] = useState<FeeBasis>();
  const filters = { page: state.page, page_size: state.pageSize };
  const query = useQuery({
    queryKey: ['fee-bases', 'list', communityId, house.id, filters],
    queryFn: () => api.bases(communityId, house.id, filters),
  });
  const latest = useQuery({
    queryKey: ['fee-bases', 'latest', communityId, house.id],
    queryFn: () => api.bases(communityId, house.id, { page: 1, page_size: 1 }),
  });
  const preview = useQuery({
    queryKey: ['fee-calculations', communityId, house.id, month],
    queryFn: () => api.calculate(communityId, house.id, month),
    enabled: validMonth(month),
  });
  const columns: ProColumns<FeeBasis>[] = [
    { title: '版本', render: (_, row) => `v${row.version_no}` },
    { title: '生效月份', dataIndex: 'effective_from_month' },
    { title: '用途', render: (_, row) => usageLabels[row.house_usage] },
    { title: '面积（㎡）', render: (_, row) => row.area_sqm ?? '—' },
    {
      title: '每㎡月单价',
      render: (_, row) =>
        row.unit_price_cents === null ? '—' : yuan(row.unit_price_cents),
    },
    {
      title: '固定月金额',
      render: (_, row) =>
        row.fixed_amount_cents === null ? '—' : yuan(row.fixed_amount_cents),
    },
    { title: '变更原因', dataIndex: 'change_reason', ellipsis: true },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => (
        <Space>
          <Button type="link" onClick={() => setDetail(row)}>
            查看版本
          </Button>
          {hasPermission('property.fee_basis.create') && (
            <Button
              type="link"
              disabled={!house.effective_enabled || !latest.isSuccess}
              onClick={() => setEditor({ copy: row })}
            >
              复制为新版本
            </Button>
          )}
        </Space>
      ),
    },
  ];
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <Card
        title="按月试算"
        extra={
          <Input
            aria-label="试算月份"
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        }
      >
        {preview.isError ? (
          <ReadError
            error={preview.error}
            retry={() => void preview.refetch()}
          />
        ) : preview.data?.available && preview.data.basis ? (
          <>
            <BasisProof basis={preview.data.basis} />
            <p>
              本月应收：<strong>{yuan(preview.data.receivable_cents!)}</strong>
            </p>
          </>
        ) : (
          <p>{preview.isFetching ? '试算中…' : '所选月份没有适用依据'}</p>
        )}
      </Card>
      {latest.isError && (
        <ReadError error={latest.error} retry={() => void latest.refetch()} />
      )}
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      <ProTable<FeeBasis>
        rowKey="id"
        headerTitle={`不可变依据版本（最新 v${latest.data?.items[0]?.version_no ?? 0}）`}
        search={false}
        columns={columns}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 1100 }}
        options={{ reload: () => void query.refetch() }}
        locale={{ emptyText: <ListEmpty filtered={false} /> }}
        toolBarRender={() =>
          hasPermission('property.fee_basis.create')
            ? [
                <Button
                  key="add"
                  type="primary"
                  disabled={!house.effective_enabled || !latest.isSuccess}
                  onClick={() => setEditor({})}
                >
                  新增依据版本
                </Button>,
              ]
            : []
        }
      />
      {editor && (
        <BasisEditor
          communityId={communityId}
          house={house}
          latest={latest.data?.items[0]?.version_no ?? 0}
          copy={editor.copy}
          done={() => setEditor(undefined)}
        />
      )}
      {detail && (
        <Drawer
          open
          title={`计费依据 v${detail.version_no}`}
          size={600}
          onClose={() => setDetail(undefined)}
        >
          <BasisProof basis={detail} />
          <p>创建于 {new Date(detail.created_at).toLocaleString()}</p>
          <p>版本 ID：{detail.id}</p>
        </Drawer>
      )}
    </Space>
  );
}
