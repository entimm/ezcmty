import { useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Form, Input, Select, Spin } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { usePropertySession } from '../hooks';
import { useHousingApi } from '../housing/hooks';
import type { House } from '../housing/api';
import { billRoot, type BillWriteResult, type Calculation } from './api';
import { BasisProof, ReasonInput } from './BillParts';
import { useBillingApi } from './hooks';
import {
  money,
  moneyRule,
  monthRule,
  parseMoney,
  receiptDateRule,
  textRule,
  validMonth,
  yuan,
} from './values';
import { WriteDrawer } from './WriteDrawer';

interface Values {
  house_id: string;
  billing_month: string;
  amount_source: 'basis' | 'manual';
  receivable?: string;
  manual_amount_reason?: string;
  basis_version_id?: string;
  external_bill_no?: string;
  due_date?: string;
  initial_paid: 'none' | 'partial' | 'full';
  paid?: string;
  received_on?: string;
  receipt_reason?: string;
}
export function CreateBillDrawer({
  communityId,
  house,
  prefill,
  done,
}: {
  communityId: string;
  house?: House;
  prefill?: {
    house_id: string;
    billing_month: string;
    house_label_snapshot: string;
  };
  done: (result?: BillWriteResult) => void;
}) {
  const api = useBillingApi();
  const housing = useHousingApi();
  const { hasPermission } = usePropertySession();
  const [form] = Form.useForm<Values>();
  const houseId = Form.useWatch('house_id', form) as string | undefined;
  const month = Form.useWatch('billing_month', form) as string | undefined;
  const source = Form.useWatch('amount_source', form) as
    Values['amount_source'] | undefined;
  const initialPaid = Form.useWatch('initial_paid', form) as
    Values['initial_paid'] | undefined;
  const manual = Form.useWatch('receivable', form) as string | undefined;
  const paidInput = Form.useWatch('paid', form) as string | undefined;
  const [search, setSearch] = useState('');
  const houses = useInfiniteQuery({
    queryKey: ['houses', 'billing-options', communityId, search],
    queryFn: ({ pageParam }) =>
      housing.houses(communityId, {
        page: pageParam,
        page_size: 100,
        room_no: search,
      }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled: !house && hasPermission('property.house.read'),
  });
  const preview = useQuery({
    queryKey: ['fee-calculations', communityId, houseId, month],
    queryFn: () => api.calculate(communityId, houseId!, month!),
    enabled:
      !!houseId &&
      validMonth(month) &&
      hasPermission('property.fee_basis.read'),
    staleTime: 0,
  });
  const bases = useInfiniteQuery({
    queryKey: ['fee-bases', 'options', communityId, houseId],
    queryFn: ({ pageParam }) =>
      api.bases(communityId, houseId!, { page: pageParam, page_size: 100 }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled:
      source === 'manual' &&
      !!houseId &&
      hasPermission('property.fee_basis.read'),
  });
  const calculation: Calculation | undefined =
    preview.data?.billing_month === month ? preview.data : undefined;
  let receivable: number | undefined;
  try {
    receivable =
      source === 'manual'
        ? parseMoney(manual ?? '')
        : (calculation?.receivable_cents ?? undefined);
  } catch {
    /* Incomplete input. */
  }
  let paid: number | undefined;
  try {
    paid =
      initialPaid === 'full'
        ? receivable
        : initialPaid === 'partial'
          ? parseMoney(paidInput ?? '', true)
          : 0;
  } catch {
    paid = undefined;
  }
  const options = new Map(
    houses.data?.pages
      .flatMap((page) => page.items)
      .map((item) => [item.id, item]) ?? [],
  );
  if (house) options.set(house.id, house);
  return (
    <WriteDrawer<Values>
      title="新增物业费账单"
      form={form}
      initialValues={{
        house_id: house?.id ?? prefill?.house_id,
        billing_month: prefill?.billing_month,
        amount_source: hasPermission('property.fee_basis.read')
          ? 'basis'
          : 'manual',
        initial_paid: 'none',
      }}
      done={done}
      prepare={(values) => {
        if (houseId !== values.house_id || month !== values.billing_month)
          throw new Error('房屋或月份已变化，请重新核对');
        const amount =
          values.amount_source === 'manual'
            ? parseMoney(values.receivable ?? '')
            : (calculation?.receivable_cents ?? undefined);
        if (amount === undefined) throw new Error('请先确认应收金额');
        if (
          values.amount_source === 'basis' &&
          (!calculation?.available ||
            preview.isFetching ||
            preview.isError ||
            !calculation.basis)
        )
          throw new Error('请等待有效计费预览');
        if (amount === 0 && values.initial_paid !== 'none')
          throw new Error('零元账单无需登记收款');
        const paidAmount =
          values.initial_paid === 'full'
            ? amount
            : values.initial_paid === 'partial'
              ? parseMoney(values.paid ?? '', true)
              : 0;
        if (paidAmount > amount) throw new Error('已缴金额不能超过应收金额');
        return {
          path: billRoot(communityId),
          method: 'POST',
          label: '新增账单',
          body: {
            house_id: values.house_id,
            billing_month: values.billing_month,
            amount_source: values.amount_source,
            ...(values.amount_source === 'basis'
              ? {
                  basis_version_id: calculation!.basis!.id,
                  expected_calculation_rule_version:
                    calculation!.calculation_rule_version,
                  expected_receivable_cents: amount,
                }
              : {
                  receivable_cents: amount,
                  manual_amount_reason: values.manual_amount_reason?.trim(),
                  basis_version_id: values.basis_version_id || null,
                }),
            external_bill_no: values.external_bill_no?.trim() || null,
            due_date: values.due_date || null,
            ...(paidAmount > 0
              ? {
                  initial_receipt: {
                    amount_cents: paidAmount,
                    received_on: values.received_on || null,
                    reason: values.receipt_reason?.trim() || null,
                  },
                }
              : {}),
          },
        };
      }}
    >
      <Form.Item
        name="house_id"
        label="房屋"
        rules={[{ required: true, message: '请选择房屋' }]}
      >
        <Select
          aria-label="房屋"
          disabled={!!house}
          placeholder="按房号搜索房屋"
          showSearch={{ filterOption: false, onSearch: setSearch }}
          loading={houses.isFetching}
          onChange={() => form.setFieldsValue({ basis_version_id: undefined })}
          options={[
            ...[...options.values()].map((item) => ({
              value: item.id,
              label: item.display_address,
              disabled: !item.effective_enabled,
            })),
            ...(prefill && !options.has(prefill.house_id)
              ? [
                  {
                    value: prefill.house_id,
                    label: prefill.house_label_snapshot,
                  },
                ]
              : []),
          ]}
          popupRender={(menu) => (
            <>
              {menu}
              {houses.hasNextPage && (
                <Button
                  onClick={() => void houses.fetchNextPage()}
                  loading={houses.isFetchingNextPage}
                >
                  加载更多房屋
                </Button>
              )}
            </>
          )}
        />
      </Form.Item>
      {houses.isError && (
        <ReadError error={houses.error} retry={() => void houses.refetch()} />
      )}
      {!house && !prefill && !hasPermission('property.house.read') && (
        <Alert type="info" title="请从房屋详情建账，或申请房屋查询权限" />
      )}
      <Form.Item name="billing_month" label="账单月份" rules={[monthRule]}>
        <Input
          type="month"
          onChange={() => form.setFieldsValue({ basis_version_id: undefined })}
        />
      </Form.Item>
      <Form.Item name="amount_source" label="应收金额来源">
        <Select
          options={[
            {
              value: 'basis',
              label: '依据自动计算',
              disabled: !hasPermission('property.fee_basis.read'),
            },
            { value: 'manual', label: '手动填写' },
          ]}
        />
      </Form.Item>
      {source === 'basis' && (
        <Card size="small" title="当月计费预览" style={{ marginBottom: 16 }}>
          {preview.isFetching ? (
            <Spin />
          ) : preview.isError ? (
            <ReadError
              error={preview.error}
              retry={() => void preview.refetch()}
            />
          ) : calculation?.available && calculation.basis ? (
            <>
              <BasisProof basis={calculation.basis} />
              <p>
                本月应收：<strong>{yuan(calculation.receivable_cents!)}</strong>
              </p>
              <Button onClick={() => void preview.refetch()}>重新试算</Button>
            </>
          ) : (
            <Alert
              type="info"
              title={
                houseId && validMonth(month)
                  ? '该月份没有适用依据，请维护依据或选择手动填写'
                  : '选择房屋和月份后显示试算'
              }
            />
          )}
        </Card>
      )}
      {source === 'manual' && (
        <>
          <Form.Item
            name="receivable"
            label="应收金额（元）"
            rules={[moneyRule()]}
          >
            <Input inputMode="decimal" />
          </Form.Item>
          <Form.Item
            name="manual_amount_reason"
            label="手填金额原因"
            rules={[textRule(1000, true)]}
          >
            <ReasonInput />
          </Form.Item>
          {hasPermission('property.fee_basis.read') && (
            <Form.Item name="basis_version_id" label="参考依据（可不选）">
              <Select
                allowClear
                options={bases.data?.pages
                  .flatMap((page) => page.items)
                  .filter(
                    (item) => !!month && item.effective_from_month <= month,
                  )
                  .map((item) => ({
                    value: item.id,
                    label: `v${item.version_no} · ${item.effective_from_month}`,
                  }))}
                popupRender={(menu) => (
                  <>
                    {menu}
                    {bases.hasNextPage && (
                      <Button onClick={() => void bases.fetchNextPage()}>
                        更多版本
                      </Button>
                    )}
                  </>
                )}
              />
            </Form.Item>
          )}
          {bases.isError && (
            <ReadError error={bases.error} retry={() => void bases.refetch()} />
          )}
        </>
      )}
      <Form.Item
        name="external_bill_no"
        label="外部账单编号（可选）"
        rules={[textRule(128)]}
      >
        <Input />
      </Form.Item>
      <Form.Item name="due_date" label="到期日（可选，仅供通知）">
        <Input type="date" />
      </Form.Item>
      {hasPermission('property.bill_receipt.create') && (
        <Form.Item name="initial_paid" label="线下已缴">
          <Select
            options={[
              { value: 'none', label: '暂未缴纳' },
              {
                value: 'partial',
                label: '录入已缴金额',
                disabled: receivable === 0,
              },
              { value: 'full', label: '全额已缴', disabled: receivable === 0 },
            ]}
          />
        </Form.Item>
      )}
      {initialPaid === 'partial' && (
        <Form.Item name="paid" label="已缴金额（元）" rules={[moneyRule(true)]}>
          <Input inputMode="decimal" />
        </Form.Item>
      )}
      {initialPaid && initialPaid !== 'none' && (
        <>
          <Form.Item
            name="received_on"
            label="实际收款日期（不详可留空）"
            rules={[receiptDateRule]}
          >
            <Input type="date" />
          </Form.Item>
          <Form.Item
            name="receipt_reason"
            label="收款说明（可选）"
            rules={[textRule(1000)]}
          >
            <ReasonInput />
          </Form.Item>
        </>
      )}
      {receivable !== undefined && (
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          showIcon
          title={
            receivable === 0
              ? '零元账单创建后直接已结清，不产生收款流水'
              : `应收 ${yuan(receivable)}，已缴 ${paid === undefined ? '待填写' : yuan(paid)}，待缴 ${paid === undefined || paid > receivable ? '请核对' : yuan(receivable - paid)}`
          }
          description={
            initialPaid === 'full'
              ? `将登记全额收款 ${money(receivable)} 元`
              : undefined
          }
        />
      )}
    </WriteDrawer>
  );
}
