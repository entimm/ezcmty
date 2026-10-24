import { useEffect, useState } from 'react';
import dayjs from 'dayjs';
import {
  Alert,
  Button,
  DatePicker,
  Descriptions,
  Drawer,
  Select,
  Space,
  Table,
  Tag,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { PageHeader, Panel, DetailGrid, Status } from '../ui';
import { useResource } from '../hooks';
import { Stats, ErrorNotice, cents, time } from '../imports/presentation';
import type { FlowPageProps } from '../imports/runtime';
import type { PaymentsRuntime } from './runtime';
import type { Discrepancy, ReconciliationRun } from './types';
import { ActionDialog } from './ActionDialog';
import type { FundsAction } from './ActionDialog';
import {
  differenceNames,
  reconciliationNames,
  statementNames,
} from './presentation';
export function Reconciliation({
  runtime: r,
  page,
  params,
  go,
}: FlowPageProps & { runtime: PaymentsRuntime }) {
  const [dates, setDates] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(
    params.from && params.to ? [dayjs(params.from), dayjs(params.to)] : null,
  );
  const [status, setStatus] = useState<string | undefined>(params.status);
  const [company, setCompany] = useState<string | undefined>(params.company);
  const [statement, setStatement] = useState<string | undefined>(
    params.statement,
  );
  const [differenceStatus, setDifferenceStatus] = useState<string | undefined>(
    params.diff,
  );
  const [runId, setRunId] = useState<string>();
  const [differenceId, setDifferenceId] = useState<string>();
  const [action, setAction] = useState<FundsAction>();
  const [scheduled, setScheduled] = useState(false);
  useEffect(() => {
    setStatus(params.status);
    setCompany(params.company);
    setStatement(params.statement);
    setDifferenceStatus(params.diff);
    setDates(
      params.from && params.to ? [dayjs(params.from), dayjs(params.to)] : null,
    );
  }, [
    params.status,
    params.company,
    params.statement,
    params.diff,
    params.from,
    params.to,
  ]);
  const current = Number(params.p) || 1,
    dp = Number(params.dp) || 1;
  const filters = {
    ...(r.scope === 'platform' ? { property_company_id: params.company } : {}),
    business_date_from: params.from,
    business_date_through: params.to,
    statement_type: params.statement,
  };
  const runs = useResource(
    ['payments', 'runs', params],
    () =>
      r.api.runs({
        ...filters,
        status: params.status,
        page: current,
        page_size: 20,
      }),
    true,
    scheduled ? 2500 : undefined,
  );
  const differences = useResource(
    ['payments', 'differences', params],
    () =>
      r.api.discrepancies({
        ...filters,
        status: params.diff,
        page: dp,
        page_size: 20,
      }),
    true,
    scheduled ? 2500 : undefined,
  );
  const run = useResource(
    ['payments', 'run', runId],
    () => r.api.run(runId!),
    !!runId,
    scheduled ? 2500 : undefined,
  );
  const difference = useResource(
    ['payments', 'difference', differenceId],
    () => r.api.discrepancy(differenceId!),
    !!differenceId,
    scheduled ? 2500 : undefined,
  );
  const companies = useResource(
    ['payments', 'companies'],
    () => r.companies!(),
    r.scope === 'platform' && !!r.companies,
  );
  const refresh = async () => {
    await Promise.all([
      runs.refetch(),
      differences.refetch(),
      ...(runId ? [run.refetch()] : []),
      ...(differenceId ? [difference.refetch()] : []),
    ]);
  };
  const companyName = (id: string | null) =>
    id
      ? companies.data?.find((x) => x.id === id)?.name || id
      : '平台账户 / 待明确归属';
  const openRun = (record: ReconciliationRun) => setRunId(record.id);
  const openDifference = (record: Discrepancy) => setDifferenceId(record.id);
  const prepareRun = () => {
    if (run.data)
      setAction({
        kind: 'recheck',
        id: run.data.id,
        token: run.data.state_token,
        label: `${run.data.business_date} · ${statementNames[run.data.statement_type]} · ${run.data.id}`,
      });
  };
  const prepareDifference = (kind: 'external' | 'difference') => {
    if (difference.data)
      setAction({
        kind,
        id: difference.data.id,
        token: difference.data.state_token,
        label: `${differenceNames[difference.data.difference_type]} · ${difference.data.id}`,
      });
  };
  const submit = async (reason: string, evidence: string) => {
    if (!action || !r.writes) throw new Error('当前没有操作权限');
    const body = { reason, expected_state_token: action.token };
    const result =
      action.kind === 'recheck'
        ? await r.writes.recheck(action.id, body)
        : action.kind === 'external'
          ? await r.writes.externalResolution(action.id, {
              ...body,
              evidence_reference: evidence,
            })
          : await r.writes.recoverDifference(action.id, body);
    setScheduled(true);
    return result;
  };
  return (
    <>
      <PageHeader
        title={r.scope === 'platform' ? '资金对账' : '对账结果'}
        description={
          r.scope === 'platform'
            ? '对齐渠道与本地事实，按证据恢复原业务或记录外部处置。'
            : '本公司全部小区的受限结果，不受顶部小区选择影响；恢复与差异处置由平台处理。'
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
            刷新核对记录
          </Button>
        }
      />
      {scheduled && (
        <Alert
          style={{ marginBottom: 20 }}
          showIcon
          type="info"
          title="任务已安排，正在读取原批次和差异的实际结果"
          description="批次完成只表示本轮核对结束，不代表全部资金差异已解决。"
        />
      )}
      <Stats
        items={[
          [
            '当前页核对批次',
            runs.data?.items.length ?? '—',
            '公司收款商户范围',
          ],
          [
            '当前页已完成批次',
            runs.data?.items.filter((x) => x.status === 'completed').length ??
              '—',
            '完成与无差异分别表达',
          ],
          [
            '当前页待处理差异',
            differences.data?.items.filter((x) => x.status !== 'resolved')
              .length ?? '—',
            '按证据处理',
          ],
          [
            '当前页已解决差异',
            differences.data?.items.filter((x) => x.status === 'resolved')
              .length ?? '—',
            '保留处置依据',
          ],
        ]}
      />
      <Panel
        title="核对批次"
        extra={
          <Tag>
            {r.scope === 'property' ? '本公司受限投影' : '平台授权账户'}
          </Tag>
        }
      >
        <div className="filter-bar">
          {r.scope === 'platform' && (
            <Select
              aria-label="核对公司名称"
              placeholder="全部物业公司"
              value={company}
              onChange={setCompany}
              allowClear
              showSearch
              optionFilterProp="label"
              loading={companies.isLoading}
              options={companies.data?.map((x) => ({
                value: x.id,
                label: x.name,
              }))}
              style={{ width: 240 }}
            />
          )}
          <DatePicker.RangePicker
            value={dates}
            onChange={(values) =>
              setDates(values?.[0] && values[1] ? [values[0], values[1]] : null)
            }
            placeholder={['业务开始日期', '业务结束日期']}
          />
          <Select
            value={statement}
            onChange={setStatement}
            allowClear
            placeholder="全部账单类型"
            style={{ width: 150 }}
            options={Object.entries(statementNames)
              .filter(
                ([key]) =>
                  r.scope === 'platform' || key !== 'platform_fundflow',
              )
              .map(([value, label]) => ({ value, label }))}
          />
          <Select
            value={status}
            onChange={setStatus}
            allowClear
            placeholder="全部核对状态"
            style={{ width: 150 }}
            options={['ready', 'running', 'completed', 'failed'].map(
              (value) => ({ value, label: reconciliationNames[value] }),
            )}
          />
          <Button
            type="primary"
            onClick={() =>
              go(page, {
                company,
                status,
                statement,
                diff: differenceStatus,
                from: dates?.[0].format('YYYY-MM-DD'),
                to: dates?.[1].format('YYYY-MM-DD'),
              })
            }
          >
            查询
          </Button>
          <Button
            onClick={() => {
              setDates(null);
              setStatus(undefined);
              setCompany(undefined);
              setStatement(undefined);
              setDifferenceStatus(undefined);
              go(page);
            }}
          >
            重置
          </Button>
        </div>
        <ErrorNotice error={runs.error} retry={() => void runs.refetch()} />
        <ErrorNotice error={companies.error} />
        <Table<ReconciliationRun>
          rowKey="id"
          loading={runs.isLoading}
          dataSource={runs.data?.items}
          pagination={{
            current,
            pageSize: 20,
            total: runs.data?.total,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 批`,
            onChange: (p) => go(page, { ...params, p: String(p) }),
          }}
          scroll={{ x: 1000 }}
          columns={[
            {
              title: '批次编号',
              dataIndex: 'id',
              render: (value, item) => (
                <Button
                  type="link"
                  style={{ padding: 0 }}
                  onClick={() => openRun(item)}
                >
                  {value}
                </Button>
              ),
            },
            ...(r.scope === 'platform'
              ? [
                  {
                    title: '所属公司',
                    dataIndex: 'property_company_id',
                    render: companyName,
                  },
                ]
              : []),
            { title: '业务日期', dataIndex: 'business_date' },
            {
              title: '账单类型',
              dataIndex: 'statement_type',
              render: (value) => statementNames[value],
            },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value) => <Status>{reconciliationNames[value]}</Status>,
            },
            {
              title: '当前差异',
              render: (_, item) => item.summary.discrepancy_count,
              align: 'right',
            },
            {
              title: '账户范围',
              render: (_, item) =>
                item.projection === 'company'
                  ? '本公司受限投影'
                  : item.merchant_no || '平台服务商账户',
            },
            {
              title: '操作',
              render: (_, item) => (
                <Button type="link" onClick={() => openRun(item)}>
                  查看批次
                </Button>
              ),
            },
          ]}
        />
      </Panel>
      <Panel
        title="差异清单"
        extra={
          <Space>
            <Select
              aria-label="差异状态"
              value={differenceStatus}
              placeholder="全部差异状态"
              allowClear
              style={{ width: 160 }}
              onChange={(value) => {
                setDifferenceStatus(value);
                go(page, { ...params, diff: value, dp: undefined });
              }}
              options={['open', 'observing', 'resolved'].map((value) => ({
                value,
                label: reconciliationNames[value],
              }))}
            />
            <span style={{ color: '#64748b' }}>按可信依据处置</span>
          </Space>
        }
      >
        <ErrorNotice
          error={differences.error}
          retry={() => void differences.refetch()}
        />
        <Table<Discrepancy>
          rowKey="id"
          loading={differences.isLoading}
          dataSource={differences.data?.items}
          pagination={{
            current: dp,
            pageSize: 20,
            total: differences.data?.total,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 项`,
            onChange: (p) => go(page, { ...params, dp: String(p) }),
          }}
          scroll={{ x: 1000 }}
          columns={[
            {
              title: '差异 / 关联支付',
              render: (_, item) => (
                <>
                  <strong>{differenceNames[item.difference_type]}</strong>
                  <div style={{ marginTop: 5, fontSize: 12, color: '#64748b' }}>
                    {item.id}
                    <br />
                    {item.evidence.order_no ||
                      item.payment_order_id ||
                      '尚未可靠关联本地支付'}
                  </div>
                </>
              ),
            },
            ...(r.scope === 'platform'
              ? [
                  {
                    title: '所属公司',
                    dataIndex: 'property_company_id',
                    render: companyName,
                  },
                ]
              : []),
            {
              title: '应有事实',
              render: (_, item) => (
                <>
                  {cents(item.expected_cents)}
                  <div style={{ color: '#64748b' }}>
                    {item.evidence.expected_status || '待核对'}
                  </div>
                </>
              ),
            },
            {
              title: '当前事实',
              render: (_, item) => (
                <>
                  {cents(item.actual_cents)}
                  <div style={{ color: '#64748b' }}>
                    {item.evidence.actual_status || '待核对'}
                  </div>
                </>
              ),
            },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value) => <Status>{reconciliationNames[value]}</Status>,
            },
            {
              title: '操作',
              render: (_, item) => (
                <Button type="link" onClick={() => openDifference(item)}>
                  查看依据
                </Button>
              ),
            },
          ]}
        />
        {r.scope === 'property' && (
          <Alert
            type="info"
            showIcon
            title="仅展示本公司可归属的结果；需要恢复时，请联系平台并提供差异编号。"
          />
        )}
      </Panel>
      <Drawer
        title="核对批次"
        open={!!runId}
        size={640}
        onClose={() => setRunId(undefined)}
        footer={
          r.writes &&
          r.can('payment_reconciliation.recheck') &&
          run.data && (
            <Button
              type="primary"
              disabled={run.data.status === 'running'}
              onClick={prepareRun}
            >
              重新核对原批次
            </Button>
          )
        }
      >
        <ErrorNotice error={run.error} retry={() => void run.refetch()} />
        {run.data && (
          <>
            <DetailGrid
              items={[
                ['批次号', run.data.id],
                ['业务日期', run.data.business_date],
                ['状态', reconciliationNames[run.data.status]],
                ['账单类型', statementNames[run.data.statement_type]],
                [
                  '核对范围',
                  run.data.projection === 'company'
                    ? '本公司受限投影'
                    : '平台授权账户',
                ],
                ['收款商户', run.data.merchant_no || '平台服务商账户'],
                ['来源摘要', run.data.source_digest || '尚未取得'],
                ['完成时间', time(run.data.finished_at)],
              ]}
            />
            <Descriptions
              style={{ marginTop: 24 }}
              column={2}
              title="可信核对汇总"
              items={[
                ['本地笔数', run.data.summary.local_count],
                ['渠道笔数', run.data.summary.channel_count],
                ['匹配笔数', run.data.summary.matched_count],
                ['差异数量', run.data.summary.discrepancy_count],
                ['本地金额', cents(run.data.summary.local_amount_cents)],
                ['渠道金额', cents(run.data.summary.channel_amount_cents)],
                ['渠道手续费', cents(run.data.summary.channel_fee_cents)],
              ].map(([label, children]) => ({
                key: String(label),
                label,
                children,
              }))}
            />
            <Alert
              type="info"
              showIcon
              title="批次已完成只表示本轮核对结束，不代表所有资金差异已解决。"
              description="重新核对复用原批次与历史账户范围，不用当前商户替换历史商户。"
              style={{ marginTop: 24 }}
            />
          </>
        )}
      </Drawer>
      <Drawer
        title="核对差异与证据"
        open={!!differenceId}
        size={680}
        onClose={() => setDifferenceId(undefined)}
        footer={
          r.writes &&
          r.can('payment_funds.recover') &&
          difference.data &&
          difference.data.status !== 'resolved' ? (
            <Space>
              {difference.data.payment_order_id && (
                <Button onClick={() => prepareDifference('difference')}>
                  恢复原业务
                </Button>
              )}
              <Button
                type="primary"
                onClick={() => prepareDifference('external')}
              >
                记录外部处置
              </Button>
            </Space>
          ) : undefined
        }
      >
        <ErrorNotice
          error={difference.error}
          retry={() => void difference.refetch()}
        />
        {difference.data && (
          <>
            <Status>{reconciliationNames[difference.data.status]}</Status>
            <Descriptions
              column={1}
              style={{ marginTop: 20 }}
              items={[
                {
                  key: 'company',
                  label: '所属范围',
                  children:
                    r.scope === 'property'
                      ? '本公司受限投影'
                      : companyName(difference.data.property_company_id),
                },
                { key: 'id', label: '差异编号', children: difference.data.id },
                {
                  key: 'order',
                  label: '关联支付',
                  children: difference.data.payment_order_id ? (
                    <Button
                      type="link"
                      style={{ padding: 0 }}
                      onClick={() => {
                        setDifferenceId(undefined);
                        go('payment-detail', {
                          id: difference.data!.payment_order_id!,
                        });
                      }}
                    >
                      {difference.data.evidence.order_no ||
                        difference.data.payment_order_id}
                    </Button>
                  ) : (
                    '尚未可靠关联本地支付'
                  ),
                },
                {
                  key: 'type',
                  label: '核对维度',
                  children: differenceNames[difference.data.difference_type],
                },
                {
                  key: 'source',
                  label: '核对来源',
                  children: difference.data.evidence.source,
                },
                {
                  key: 'digest',
                  label: '来源摘要',
                  children: difference.data.evidence.source_digest || '待取得',
                },
                {
                  key: 'line',
                  label: '渠道账单行',
                  children: difference.data.evidence.statement_line_no ?? '—',
                },
                {
                  key: 'expected',
                  label: '应有事实',
                  children: `${cents(difference.data.expected_cents)} · ${difference.data.evidence.expected_status || '待核对'}`,
                },
                {
                  key: 'actual',
                  label: '当前事实',
                  children: `${cents(difference.data.actual_cents)} · ${difference.data.evidence.actual_status || '待核对'}`,
                },
                {
                  key: 'checked',
                  label: '核对时间',
                  children: time(difference.data.evidence.checked_at),
                },
                {
                  key: 'resolution',
                  label: '处置说明',
                  children: difference.data.resolution_note || '尚未记录',
                },
                {
                  key: 'resolved',
                  label: '解决时间',
                  children: time(difference.data.resolved_at),
                },
              ]}
            />
            <Alert
              showIcon
              type="warning"
              title="外部处置仅记录核实结论，不更改支付、账单入账、分账、解冻或支付占用。"
              style={{ marginTop: 20 }}
            />
            {r.scope === 'property' && (
              <p style={{ color: '#64748b', marginTop: 20 }}>
                需要恢复时请联系平台并提供差异编号。
              </p>
            )}
          </>
        )}
      </Drawer>
      {action && r.writes && (
        <ActionDialog
          action={action}
          close={() => setAction(undefined)}
          submit={submit}
          setDirty={r.setDirty}
          verify={refresh}
        />
      )}
    </>
  );
}
