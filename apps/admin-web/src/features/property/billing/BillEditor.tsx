import { useState } from 'react';
import { Alert, Button, Form, Input } from 'antd';
import { OperationError } from '../../../components/AdminFeedback';
import {
  billRoot,
  type Bill,
  type BillAction,
  type BillWriteResult,
  type SettlementEntry,
} from './api';
import { useBillingApi } from './hooks';
import { ReasonInput } from './BillParts';
import {
  actionLabels,
  money,
  moneyRule,
  parseMoney,
  receiptDateRule,
  textRule,
  yuan,
} from './values';
import { WriteDrawer } from './WriteDrawer';

interface Values {
  amount?: string;
  received_on?: string;
  reason?: string;
  external_bill_no?: string;
  due_date?: string;
}
export function BillEditor({
  bill,
  action,
  entry,
  done,
}: {
  bill: Bill;
  action: Exclude<BillAction, 'create' | 'online_receipt'>;
  entry?: SettlementEntry;
  done: (result?: BillWriteResult) => void;
}) {
  const [form] = Form.useForm<Values>();
  const api = useBillingApi();
  const [current, setCurrent] = useState(bill);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<unknown>();
  const blocked =
    action !== 'update' &&
    (current.payment_in_progress ||
      ((action === 'correct_receipt' || action === 'reverse_receipt') &&
        entry?.source_type !== 'offline'));
  const value = Form.useWatch('amount', form) as string | undefined;
  let after: number | undefined;
  try {
    const amount = parseMoney(value ?? '', true);
    after =
      current.settled_cents -
      (action === 'correct_receipt' ? entry!.amount_cents : 0) +
      amount;
  } catch {
    /* Incomplete money input. */
  }
  return (
    <WriteDrawer<Values>
      title={actionLabels[action]}
      form={form}
      done={done}
      disabled={blocked}
      initialValues={{
        external_bill_no: current.external_bill_no ?? '',
        due_date: current.due_date ?? '',
        amount:
          action === 'correct_receipt' && entry
            ? money(entry.amount_cents)
            : undefined,
        received_on:
          action === 'correct_receipt' ? (entry?.received_on ?? '') : '',
      }}
      prepare={(values) => {
        if (current.lifecycle_status !== 'active')
          throw new Error('账单已作废，请关闭后查看最新详情');
        if (action !== 'update' && current.payment_in_progress)
          throw new Error('该账单有支付正在处理中，请先核实原订单');
        if (
          (action === 'correct_receipt' || action === 'reverse_receipt') &&
          entry?.source_type !== 'offline'
        )
          throw new Error('线上支付收款不能通过线下纠错或撤销处理');
        const base = { expected_row_version: current.row_version };
        const root = billRoot(current.community_id, current.id);
        if (action === 'update')
          return {
            path: root,
            method: 'PATCH',
            label: actionLabels[action],
            body: {
              ...base,
              external_bill_no: values.external_bill_no?.trim() || null,
              due_date: values.due_date || null,
            },
          };
        const reason = values.reason?.trim() || null;
        if (action === 'void')
          return {
            path: `${root}/voids`,
            method: 'POST',
            label: actionLabels[action],
            body: { ...base, reason },
          };
        if (action === 'reverse_receipt')
          return {
            path: `${root}/offline-receipts/${entry!.id}/reversals`,
            method: 'POST',
            label: actionLabels[action],
            body: { ...base, reason },
          };
        const amount = parseMoney(values.amount ?? '', true);
        if (
          amount >
          current.receivable_cents -
            current.settled_cents +
            (action === 'correct_receipt' ? entry!.amount_cents : 0)
        )
          throw new Error('登记金额超过账单应收范围');
        return {
          path:
            action === 'receipt'
              ? `${root}/offline-receipts`
              : `${root}/offline-receipts/${entry!.id}/corrections`,
          method: 'POST',
          label: actionLabels[action],
          body:
            action === 'receipt'
              ? {
                  ...base,
                  amount_cents: amount,
                  received_on: values.received_on || null,
                  reason,
                }
              : {
                  ...base,
                  corrected_amount_cents: amount,
                  corrected_received_on: values.received_on || null,
                  reason,
                },
        };
      }}
    >
      <OperationError error={error} />
      {blocked && (
        <Alert
          style={{ marginBottom: 16 }}
          type="warning"
          showIcon
          title={
            current.payment_in_progress
              ? '该账单有支付正在处理中，请先核实原订单'
              : '线上支付收款不能通过线下纠错或撤销处理'
          }
        />
      )}
      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        title={`${current.billing_month} · ${current.house_label_snapshot}`}
        description={`应收 ${yuan(current.receivable_cents)}，已缴 ${yuan(current.settled_cents)}，待缴 ${yuan(current.outstanding_cents)}；当前版本 ${current.row_version}`}
      />
      <Button
        style={{ marginBottom: 16 }}
        loading={refreshing}
        onClick={async () => {
          setRefreshing(true);
          setError(undefined);
          try {
            setCurrent(await api.bill(current.community_id, current.id));
          } catch (caught) {
            setError(caught);
          } finally {
            setRefreshing(false);
          }
        }}
      >
        刷新账单并重新核对
      </Button>
      {action === 'update' ? (
        <>
          <Form.Item
            name="external_bill_no"
            label="外部账单编号"
            rules={[textRule(128)]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="due_date" label="到期日">
            <Input type="date" />
          </Form.Item>
        </>
      ) : (
        <>
          {entry && (
            <Alert
              style={{ marginBottom: 16 }}
              type="info"
              title={`原收款 ${yuan(entry.amount_cents)} · ${entry.received_on ?? '日期不详'}`}
              description="原条目将完整保留，并追加等额冲正。撤销登记不表示退款。"
            />
          )}
          {action === 'void' && (
            <Alert
              style={{ marginBottom: 16 }}
              type="warning"
              title="作废后不可修改，可按原房屋和月份重新建账"
              description="有有效收款时需先纠正误登记；实际已缴账单不能直接作废。"
            />
          )}
          {(action === 'receipt' || action === 'correct_receipt') && (
            <>
              <Form.Item
                name="amount"
                label={
                  action === 'receipt' ? '本次收款（元）' : '正确收款金额（元）'
                }
                rules={[moneyRule(true)]}
              >
                <Input inputMode="decimal" />
              </Form.Item>
              {action === 'receipt' && (
                <Button
                  style={{ marginBottom: 16 }}
                  onClick={() =>
                    form.setFieldValue(
                      'amount',
                      money(current.outstanding_cents),
                    )
                  }
                >
                  填入剩余金额
                </Button>
              )}
              <Form.Item
                name="received_on"
                label="实际收款日期（不详可留空）"
                rules={[receiptDateRule]}
              >
                <Input type="date" />
              </Form.Item>
              {after !== undefined && (
                <Alert
                  style={{ marginBottom: 16 }}
                  type={after > current.receivable_cents ? 'error' : 'info'}
                  title={
                    after > current.receivable_cents
                      ? '金额超过应收，请核对'
                      : `操作后已缴 ${yuan(after)}，待缴 ${yuan(current.receivable_cents - after)}`
                  }
                />
              )}
            </>
          )}
          <Form.Item
            name="reason"
            label={action === 'receipt' ? '收款说明（可选）' : '操作原因'}
            rules={[textRule(1000, action !== 'receipt')]}
          >
            <ReasonInput />
          </Form.Item>
        </>
      )}
    </WriteDrawer>
  );
}
