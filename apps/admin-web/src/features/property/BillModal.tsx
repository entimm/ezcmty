import { useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Col,
  DatePicker,
  Divider,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
  Spin,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useAdmin } from '../../shared/context';
import { ApiError } from '../../shared/request';
import {
  createPropertyApi,
  billRoot,
  type Bill,
  type BillSubmission,
  type BillWriteResult,
  type House,
} from './api';
import type { BillEditorState } from './Billing';
import { PropertyEditor } from './Editor';
import {
  basisText,
  businessToday,
  cents,
  QueryError,
  toCents,
} from './presentation';

interface PendingWrite {
  key: string;
  submission: BillSubmission;
}
const permissions = {
  edit: 'property.bill.update',
  receipt: 'property.bill_receipt.create',
  correct: 'property.bill_receipt.correct',
  reverse: 'property.bill_receipt.correct',
  void: 'property.bill.void',
};
const titles = {
  edit: '编辑账单资料',
  receipt: '登记线下收款',
  correct: '收款登记纠错',
  reverse: '撤销收款登记',
  void: '作废账单',
};
const confirmLabels = {
  edit: '保存账单资料',
  receipt: '确认登记收款',
  correct: '保存纠错结果',
  reverse: '确认撤销登记',
  void: '确认作废',
};

export function BillModal({
  editor,
  house,
  original,
  close,
}: {
  editor?: BillEditorState;
  house?: House;
  original?: Bill;
  close: () => void;
}) {
  const { request, can, communityId, params, setDirty } = useAdmin();
  const { message } = App.useApp();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const cache = useQueryClient();
  const [form] = Form.useForm();
  const [search, setSearch] = useState('');
  const [optionsPage, setOptionsPage] = useState(1);
  const [pending, setPending] = useState<PendingWrite>();
  const [recovering, setRecovering] = useState(false);
  const [recoveryText, setRecoveryText] =
    useState('写入结果暂未确定，请先核实原操作。');
  const submitting = useRef(false);
  const bill = editor?.bill;
  const action = editor?.action;
  const c =
    bill?.community_id ||
    house?.community_id ||
    original?.community_id ||
    communityId ||
    params.community_id ||
    '';
  const houseId = Form.useWatch('house_id', form) as string | undefined;
  const month = Form.useWatch('month', form) as Dayjs | undefined;
  const source = Form.useWatch('source', form) as string | undefined;
  const amount = Form.useWatch('amount', form) as number | undefined;
  const initialHouseId = house?.id || original?.house_id;
  const selectedHouse = useQuery({
    queryKey: ['property', 'bill-selected-house', c, houseId || initialHouseId],
    queryFn: () => api.house(c, (houseId || initialHouseId)!),
    enabled:
      !editor &&
      !!c &&
      !!(houseId || initialHouseId) &&
      can('property.house.read'),
  });
  const houseOptions = useQuery({
    queryKey: ['property', 'bill-house-options', c, search, optionsPage],
    queryFn: () =>
      api.houses(c, {
        page: optionsPage,
        page_size: 50,
        room_no: search || undefined,
        enabled: true,
      }),
    enabled: !editor && !!c && can('property.house.read'),
  });
  const calculation = useQuery({
    queryKey: [
      'property',
      'bill-create-calculation',
      c,
      houseId || initialHouseId,
      month?.format('YYYY-MM'),
    ],
    queryFn: () =>
      api.calculate(c, (houseId || initialHouseId)!, month!.format('YYYY-MM')),
    enabled:
      !editor &&
      can('property.fee_basis.read') &&
      source === 'basis' &&
      !!(houseId || initialHouseId) &&
      !!month &&
      !!c,
    retry: false,
  });
  const initial: Record<string, unknown> = editor
    ? {
        external: bill?.external_bill_no ?? '',
        due: bill?.due_date ? dayjs(bill.due_date) : null,
        amount:
          action === 'receipt'
            ? bill!.outstanding_cents / 100
            : action === 'correct'
              ? editor.entry!.amount_cents / 100
              : undefined,
        received:
          action === 'correct'
            ? editor.entry?.received_on
              ? dayjs(editor.entry.received_on)
              : null
            : dayjs(businessToday()),
      }
    : {
        house_id: initialHouseId,
        month: original
          ? dayjs(original.billing_month)
          : dayjs().add(1, 'month').startOf('month'),
        due: original?.due_date
          ? dayjs(original.due_date)
          : dayjs().add(1, 'month').endOf('month'),
        source: can('property.fee_basis.read') ? 'basis' : 'manual',
        paid: 0,
      };
  const maximum = bill
    ? bill.outstanding_cents +
      (action === 'correct' ? (editor?.entry?.amount_cents ?? 0) : 0)
    : 0;
  const success = async (result: BillWriteResult) => {
    setPending(undefined);
    await cache.invalidateQueries({ queryKey: ['property'] });
    message.success(
      editor ? `${titles[editor.action]}成功` : '账单已创建并立即生效',
    );
    setDirty(false);
    close();
    return result;
  };
  const perform = async (operation: PendingWrite) => {
    if (submitting.current) return;
    submitting.current = true;
    try {
      await success(await api.submitBill(operation.submission, operation.key));
    } catch (failure) {
      if (
        failure instanceof ApiError &&
        failure.status >= 400 &&
        failure.status < 500 &&
        failure.status !== 408
      ) {
        setPending(undefined);
        if (failure.status === 409)
          await cache.invalidateQueries({ queryKey: ['property'] });
      } else {
        setPending(operation);
        setDirty(true);
        setRecoveryText(
          '网络或服务异常，尚未确认写入结果。请先核实，必要时使用原请求和原幂等键重试。',
        );
      }
      throw failure;
    } finally {
      submitting.current = false;
    }
  };
  const submit = async (values: Record<string, unknown>) => {
    if (pending) throw new Error('请先核实原操作结果');
    if (!c) throw new Error('请选择小区');
    let submission: BillSubmission;
    if (editor) {
      if (!can(permissions[editor.action])) throw new Error('没有此操作权限');
      if (bill!.lifecycle_status !== 'active')
        throw new Error('账单已作废，不能继续修改');
      if (editor.action !== 'edit' && bill!.payment_in_progress)
        throw new Error('居民支付正在处理中，请等待原订单结果');
      const root = billRoot(c, bill!.id);
      const version = { expected_row_version: bill!.row_version };
      const reason =
        typeof values.reason === 'string' ? values.reason.trim() || null : null;
      if (editor.action === 'edit')
        submission = {
          path: root,
          method: 'PATCH',
          body: {
            ...version,
            external_bill_no:
              typeof values.external === 'string'
                ? values.external.trim() || null
                : null,
            due_date:
              (values.due as Dayjs | null)?.format('YYYY-MM-DD') ?? null,
          },
        };
      else if (editor.action === 'void') {
        if (bill!.settled_cents !== 0)
          throw new Error('账单已存在收款，请先核实');
        submission = {
          path: `${root}/voids`,
          method: 'POST',
          body: { ...version, reason },
        };
      } else if (editor.action === 'reverse') {
        if (
          editor.entry?.source_type !== 'offline' ||
          editor.entry.entry_type !== 'receipt' ||
          editor.entry.reversed_by_entry_id
        )
          throw new Error('仅可撤销尚未冲正的线下收款');
        submission = {
          path: `${root}/offline-receipts/${editor.entry.id}/reversals`,
          method: 'POST',
          body: { ...version, reason },
        };
      } else {
        const entered = toCents(values.amount, true);
        if (entered > maximum) throw new Error('登记金额超过账单应收范围');
        const receivedOn =
          (values.received as Dayjs | null)?.format('YYYY-MM-DD') ?? null;
        if (receivedOn && receivedOn > businessToday())
          throw new Error('收款日期不能晚于今天');
        if (editor.action === 'receipt') {
          if (!bill!.house_effective_enabled)
            throw new Error('房屋或上级已停用，暂不能登记收款');
          submission = {
            path: `${root}/offline-receipts`,
            method: 'POST',
            body: {
              ...version,
              amount_cents: entered,
              received_on: receivedOn,
              reason,
            },
          };
        } else {
          if (
            editor.entry?.source_type !== 'offline' ||
            editor.entry.entry_type !== 'receipt' ||
            editor.entry.reversed_by_entry_id
          )
            throw new Error('仅可纠正尚未冲正的线下收款');
          submission = {
            path: `${root}/offline-receipts/${editor.entry.id}/corrections`,
            method: 'POST',
            body: {
              ...version,
              corrected_amount_cents: entered,
              corrected_received_on: receivedOn,
              reason,
            },
          };
        }
      }
    } else {
      if (!can('property.bill.create')) throw new Error('没有建账权限');
      const chosenId = String(values.house_id || initialHouseId || '');
      if (!chosenId || !selectedHouse.data?.effective_enabled)
        throw new Error('请选择当前可用房屋');
      const body: Record<string, unknown> = {
        house_id: chosenId,
        billing_month: (values.month as Dayjs).format('YYYY-MM'),
        amount_source: values.source,
        external_bill_no:
          typeof values.external === 'string'
            ? values.external.trim() || null
            : null,
        due_date: (values.due as Dayjs | null)?.format('YYYY-MM-DD') ?? null,
      };
      let receivable: number;
      if (values.source === 'basis') {
        if (
          !calculation.data?.available ||
          !calculation.data.basis ||
          calculation.data.receivable_cents === null
        )
          throw new Error('暂无可用试算结果，请先维护计费依据或改为手动填写');
        body.basis_version_id = calculation.data.basis.id;
        body.expected_calculation_rule_version =
          calculation.data.calculation_rule_version;
        body.expected_receivable_cents = calculation.data.receivable_cents;
        receivable = calculation.data.receivable_cents;
      } else {
        receivable = toCents(values.amount);
        body.receivable_cents = receivable;
        body.manual_amount_reason =
          typeof values.reason === 'string' ? values.reason.trim() : '';
      }
      const paid = toCents(values.paid ?? 0);
      if (paid > receivable) throw new Error('初始收款不能超过应收金额');
      if (paid > 0) {
        if (!can('property.bill_receipt.create'))
          throw new Error('没有初始收款登记权限');
        body.initial_receipt = {
          amount_cents: paid,
          received_on: null,
          reason: '建账时登记初始线下收款',
        };
      }
      submission = { path: billRoot(c), method: 'POST', body };
    }
    await perform({ key: crypto.randomUUID(), submission });
  };
  const recover = async (retry = false) => {
    if (!pending || recovering || submitting.current) return;
    setRecovering(true);
    try {
      if (retry) await perform(pending);
      else await success((await api.billResult(pending.key)).result);
    } catch (failure) {
      setRecoveryText(
        failure instanceof ApiError && failure.status === 404
          ? '尚未查到首次成功结果。可再次核实，或使用下方“重试原操作”保持同一请求与幂等键。'
          : failure instanceof Error
            ? failure.message
            : '结果核实失败，请稍后继续核实',
      );
    } finally {
      setRecovering(false);
    }
  };
  const reasonField = (required = true, label = '操作原因') => (
    <Form.Item
      name="reason"
      label={label}
      rules={[
        { required, whitespace: true, message: `请填写${label}` },
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
  );
  return (
    <PropertyEditor
      title={action ? titles[action] : '新增物业费账单'}
      form={form}
      initial={initial}
      submit={submit}
      close={close}
      width={editor ? 600 : 760}
      confirmLabel={action ? confirmLabels[action] : '创建账单'}
      danger={action === 'reverse' || action === 'void'}
      locked={!!pending}
      extra={
        pending && (
          <Alert
            showIcon
            type="warning"
            title="正在核实原操作"
            description={recoveryText}
            style={{ marginBottom: 20 }}
            action={
              <Space orientation="vertical">
                <Button loading={recovering} onClick={() => void recover()}>
                  核实结果
                </Button>
                <Button loading={recovering} onClick={() => void recover(true)}>
                  重试原操作
                </Button>
              </Space>
            }
          />
        )
      }
    >
      {!editor && (
        <>
          <Alert
            type="info"
            showIcon
            title="创建后立即生效，请仔细核对房屋、月份及应收金额。"
            style={{ marginBottom: 20 }}
          />
          <QueryError error={houseOptions.error} retry={houseOptions.refetch} />
          <Form.Item
            name="house_id"
            label="收费房屋"
            rules={[{ required: true, message: '请选择房屋' }]}
          >
            <Select
              showSearch
              filterOption={false}
              onSearch={(value) => {
                setSearch(value);
                setOptionsPage(1);
              }}
              placeholder="输入完整房号查询"
              loading={houseOptions.isFetching}
              options={[
                ...(selectedHouse.data ? [selectedHouse.data] : []),
                ...(houseOptions.data?.items ?? []).filter(
                  (h) => h.id !== selectedHouse.data?.id,
                ),
              ].map((h) => ({
                value: h.id,
                label: h.display_address,
                disabled: !h.effective_enabled,
              }))}
              popupRender={(menu) => (
                <>
                  {menu}
                  {houseOptions.data && houseOptions.data.total > 50 && (
                    <div style={{ padding: 8, borderTop: '1px solid #eee' }}>
                      <Space>
                        <Button
                          size="small"
                          disabled={optionsPage <= 1}
                          onClick={() => setOptionsPage(optionsPage - 1)}
                        >
                          上一页
                        </Button>
                        <span>第 {optionsPage} 页</span>
                        <Button
                          size="small"
                          disabled={optionsPage * 50 >= houseOptions.data.total}
                          onClick={() => setOptionsPage(optionsPage + 1)}
                        >
                          下一页
                        </Button>
                      </Space>
                    </div>
                  )}
                </>
              )}
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="month"
                label="账单月份"
                rules={[{ required: true, message: '请选择账单月份' }]}
              >
                <DatePicker picker="month" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="due" label="到期日期（选填）">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="source" label="应收金额来源">
            <Radio.Group
              options={[
                {
                  value: 'basis',
                  label: '计费依据自动计算',
                  disabled: !can('property.fee_basis.read'),
                },
                { value: 'manual', label: '手动填写金额' },
              ]}
            />
          </Form.Item>
          {source === 'manual' ? (
            <>
              <Form.Item
                name="amount"
                label="应收金额（元）"
                rules={[{ required: true, message: '请输入应收金额' }]}
              >
                <InputNumber min={0} precision={2} style={{ width: '100%' }} />
              </Form.Item>
              {reasonField(true, '手填金额原因')}
            </>
          ) : (
            <>
              <QueryError
                error={calculation.error}
                retry={calculation.refetch}
              />
              <Spin spinning={calculation.isFetching}>
                <div
                  style={{
                    padding: '16px 20px',
                    background: '#f3f6fd',
                    border: '1px solid #e5ebf9',
                    borderRadius: 8,
                    marginBottom: 20,
                  }}
                >
                  <div className="muted" style={{ fontSize: 12 }}>
                    {calculation.data?.basis
                      ? `依据 v${calculation.data.basis.version_no} · ${basisText(calculation.data.basis)}`
                      : '请选择房屋与月份，读取适用的计费依据'}
                  </div>
                  <div
                    style={{
                      fontSize: 28,
                      fontWeight: 650,
                      color: '#3154bb',
                      marginTop: 6,
                    }}
                  >
                    {calculation.data?.available
                      ? cents(calculation.data.receivable_cents)
                      : '暂无可用依据'}
                  </div>
                </div>
              </Spin>
            </>
          )}
          <Form.Item name="external" label="外部账单编号（选填）">
            <Input maxLength={128} />
          </Form.Item>
          {can('property.bill_receipt.create') && (
            <>
              <Divider titlePlacement="left" style={{ fontSize: 13 }}>
                已有线下收款（选填）
              </Divider>
              <Form.Item
                name="paid"
                label="建账时已缴金额（元）"
                help="无收款请保持 0。正金额将同时创建线下收款记录。"
              >
                <InputNumber
                  min={0}
                  precision={2}
                  max={
                    source === 'manual'
                      ? amount
                      : calculation.data?.receivable_cents != null
                        ? calculation.data.receivable_cents / 100
                        : undefined
                  }
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </>
          )}
        </>
      )}
      {editor && bill && (
        <>
          {action !== 'edit' && (
            <div
              style={{
                background: '#f4f7fc',
                borderRadius: 8,
                padding: 18,
                marginBottom: 22,
              }}
            >
              <strong>
                {bill.house_label_snapshot} · {bill.billing_month}
              </strong>
              <div style={{ color: '#6f7b90', marginTop: 8 }}>
                应收 {cents(bill.receivable_cents)} 已缴{' '}
                {cents(bill.settled_cents)} 待缴{' '}
                <strong style={{ color: '#b87316' }}>
                  {cents(bill.outstanding_cents)}
                </strong>
              </div>
            </div>
          )}
          {action === 'edit' && (
            <>
              <Form.Item name="external" label="外部账单编号">
                <Input maxLength={128} />
              </Form.Item>
              <Form.Item name="due" label="到期日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
              <Alert
                type="info"
                showIcon
                title="已创建账单的房屋、账期及应收金额保持不变。"
              />
            </>
          )}
          {(action === 'receipt' || action === 'correct') && (
            <>
              {action === 'correct' && (
                <Alert
                  showIcon
                  type="warning"
                  title={`原登记 ${cents(editor.entry!.amount_cents)}。保存后追加冲正，并登记正确金额。`}
                  style={{ marginBottom: 18 }}
                />
              )}
              <Form.Item
                name="amount"
                label={
                  action === 'receipt'
                    ? '本次收款金额（元）'
                    : '正确收款金额（元）'
                }
                rules={[
                  { required: true, message: '请填写收款金额' },
                  {
                    type: 'number',
                    min: 0.01,
                    max: maximum / 100,
                    message: `请输入 0.01 至 ${cents(maximum)} 的金额`,
                  },
                ]}
              >
                <InputNumber
                  min={0.01}
                  max={maximum / 100}
                  precision={2}
                  style={{ width: '100%' }}
                />
              </Form.Item>
              <Form.Item name="received" label="实际收款日期（不详可留空）">
                <DatePicker
                  disabledDate={(value) =>
                    value.format('YYYY-MM-DD') > businessToday()
                  }
                  style={{ width: '100%' }}
                />
              </Form.Item>
              {reasonField(
                action === 'correct',
                action === 'correct' ? '纠错原因' : '收款说明（选填）',
              )}
              {amount != null && (
                <Alert
                  type="info"
                  title={`操作后待缴 ${cents(Math.max(0, maximum - Math.round(amount * 100)))}`}
                />
              )}
            </>
          )}
          {action === 'reverse' && (
            <>
              <Alert
                showIcon
                type="warning"
                title="撤销登记不表示实际退款"
                description="原收款条目将完整保留，追加等额冲正。请确认本次为误登记纠正。"
                style={{ marginBottom: 20 }}
              />
              {reasonField(true, '撤销原因')}
            </>
          )}
          {action === 'void' && (
            <>
              <Alert
                showIcon
                type="warning"
                title="作废后不可修改或恢复"
                description="可按原房屋和月份重新建账。已有实际收款的账单应先核实收款记录。"
                style={{ marginBottom: 20 }}
              />
              {reasonField(true, '作废原因')}
            </>
          )}
        </>
      )}
    </PropertyEditor>
  );
}
