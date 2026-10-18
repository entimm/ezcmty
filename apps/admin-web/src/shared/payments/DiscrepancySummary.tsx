import { Alert, Descriptions } from 'antd';
import type { Discrepancy, ReconciliationRun } from './types';
import {
  differenceLabels,
  money,
  reconciliationStatuses,
} from './presentation';
export function DiscrepancySummary({ item }: { item: Discrepancy }) {
  return (
    <>
      <Alert
        type="info"
        title="差异处置与资金状态分别确认；差异已解决不表示支付、分账或解冻成功。"
      />
      <Descriptions
        column={1}
        style={{ marginTop: 16 }}
        items={[
          { key: 'reference', label: '业务引用', children: item.reference_key },
          {
            key: 'status',
            label: '当前处置',
            children: reconciliationStatuses[item.status],
          },
          {
            key: 'type',
            label: '差异',
            children: differenceLabels[item.difference_type],
          },
          {
            key: 'check',
            label: '核对维度',
            children: item.evidence.check_code,
          },
          {
            key: 'expected',
            label: '应有金额',
            children: money(item.expected_cents),
          },
          {
            key: 'actual',
            label: '实际金额',
            children: money(item.actual_cents),
          },
          {
            key: 'expected-status',
            label: '应有状态',
            children: item.evidence.expected_status || '待确认',
          },
          {
            key: 'actual-status',
            label: '实际状态',
            children: item.evidence.actual_status || '待确认',
          },
          { key: 'source', label: '判定来源', children: item.evidence.source },
          {
            key: 'digest',
            label: '该次来源摘要',
            children: item.evidence.source_digest || '不适用',
          },
          {
            key: 'request',
            label: '本地证据引用',
            children: item.evidence.source_request_id || '内部核验',
          },
          {
            key: 'checked',
            label: '判定时间',
            children: item.evidence.checked_at,
          },
          {
            key: 'run',
            label: '核对批次',
            children: item.reconciliation_run_id,
          },
          {
            key: 'order',
            label: '关联支付',
            children: item.payment_order_id || '尚未确定',
          },
          {
            key: 'last',
            label: '最近处置说明',
            children: item.resolution_note || '无',
          },
          {
            key: 'last-time',
            label: '最近处置时间',
            children: item.resolved_at || '无',
          },
        ]}
      />
    </>
  );
}
export function ReconciliationSummary({ item }: { item: ReconciliationRun }) {
  return (
    <Descriptions
      column={1}
      items={[
        { key: 'date', label: '业务日期', children: item.business_date },
        { key: 'type', label: '账单类型', children: item.statement_type },
        {
          key: 'status',
          label: '批次状态',
          children: reconciliationStatuses[item.status],
        },
        {
          key: 'merchant',
          label: '收款商户',
          children: item.merchant_no || '平台基本账户',
        },
        {
          key: 'scope',
          label: '账户范围',
          children:
            item.projection === 'company' ? '本公司投影' : '完整授权批次',
        },
        {
          key: 'source',
          label: '最近可信来源摘要',
          children: item.source_digest || '尚未取得',
        },
        {
          key: 'local',
          label: '本地金额',
          children: money(item.summary.local_amount_cents),
        },
        {
          key: 'channel',
          label: '渠道金额',
          children: money(item.summary.channel_amount_cents),
        },
        {
          key: 'fee',
          label: '渠道手续费',
          children: money(item.summary.channel_fee_cents),
        },
        {
          key: 'differences',
          label: '差异数',
          children: item.summary.discrepancy_count,
        },
      ]}
    />
  );
}
