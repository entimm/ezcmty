import { useEffect, useState } from 'react';
import dayjs from 'dayjs';
import {
  App,
  Button,
  DatePicker,
  Empty,
  Input,
  Select,
  Table,
  Tag,
} from 'antd';
import { PlusOutlined, SearchOutlined } from '@ant-design/icons';
import { PageHeader, Panel } from '../ui';
import { useResource } from '../hooks';
import { NewImport } from './NewImport';
import { ImportDetail } from './ImportDetail';
import { BatchTag, ErrorNotice, Stats, batchNames, time } from './presentation';
import type { Batch } from './types';
import type { FlowPageProps, ImportsRuntime } from './runtime';
export function ImportsPage(
  props: FlowPageProps & { runtime: ImportsRuntime },
) {
  if (props.runtime.scope === 'property' && !props.runtime.communityId)
    return (
      <>
        <PageHeader
          title="导入中心"
          description="导入按当前小区组织，批次创建后范围固定。"
        />
        <Panel>
          <Empty description="请先在上方选择小区；若无可选小区，请联系管理员。" />
        </Panel>
      </>
    );
  if (props.page === 'import-new') return <NewImport {...props} />;
  if (props.page === 'import-detail') return <ImportDetail {...props} />;
  return <ImportCenter {...props} />;
}
function ImportCenter({
  runtime: r,
  page,
  params,
  go,
}: FlowPageProps & { runtime: ImportsRuntime }) {
  const { message } = App.useApp();
  const [batchId, setBatchId] = useState('');
  const [status, setStatus] = useState<string | undefined>(params.status);
  const [dates, setDates] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(
    params.from && params.to ? [dayjs(params.from), dayjs(params.to)] : null,
  );
  const current = Number(params.p) || 1;
  const pageSize = 20;
  useEffect(() => {
    setStatus(params.status);
    setDates(
      params.from && params.to ? [dayjs(params.from), dayjs(params.to)] : null,
    );
  }, [params.status, params.from, params.to]);
  const result = useResource(
    ['imports', 'batches', r.scope, r.communityId, params],
    () =>
      r.api.batches({
        page: current,
        page_size: pageSize,
        status: params.status,
        created_from: params.from
          ? dayjs(params.from).startOf('day').toISOString()
          : undefined,
        created_before: params.to
          ? dayjs(params.to).add(1, 'day').startOf('day').toISOString()
          : undefined,
        ...(r.scope === 'property' && r.communityId
          ? { scope_type: 'community', scope_id: r.communityId }
          : {}),
      }),
  );
  const types = useResource(
    ['imports', 'types'],
    () => r.api.types(),
    r.can('create'),
  );
  const rows = result.data?.items || [];
  const open = (item: Batch) =>
    go('import-detail', { id: item.id, return: JSON.stringify(params) });
  function query() {
    if (batchId.trim()) {
      if (
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          batchId.trim(),
        )
      ) {
        message.warning('请输入完整批次 ID，或使用状态与日期查询');
        return;
      }
      go('import-detail', {
        id: batchId.trim(),
        return: JSON.stringify(params),
      });
      return;
    }
    go(page, {
      status,
      from: dates?.[0].format('YYYY-MM-DD'),
      to: dates?.[1].format('YYYY-MM-DD'),
    });
  }
  return (
    <>
      <PageHeader
        title="导入中心"
        description="集中查看批次、核对预检问题，安全处理批量资料。"
        extra={
          r.can('create') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() =>
                go('import-new', { return: JSON.stringify(params) })
              }
            >
              新建导入
            </Button>
          )
        }
      />
      {r.scope === 'property' && (
        <Stats
          items={[
            [
              '当前页批次',
              rows.length,
              r.community?.name
                ? `范围：${r.community.name}`
                : '当前公司授权范围',
            ],
            [
              '当前页待确认',
              rows.filter((x) => x.status === 'preview_ready').length,
              '预检完成，尚未执行',
            ],
            [
              '当前页已完成',
              rows.filter((x) => x.status === 'completed').length,
              '结果可追溯',
            ],
            [
              '当前页需关注',
              rows.filter((x) =>
                ['partial_failed', 'failed', 'blocked'].includes(x.status),
              ).length,
              '核实问题并安全处理',
            ],
          ]}
        />
      )}
      <Panel title="批次记录" extra={<Tag>仅创建模式</Tag>}>
        <div className="filter-bar">
          <Input
            prefix={<SearchOutlined />}
            placeholder="批次 ID（精确打开）"
            value={batchId}
            onChange={(event) => setBatchId(event.target.value)}
            onPressEnter={query}
            allowClear
            style={{ width: 260 }}
          />
          <Select
            placeholder="全部状态"
            allowClear
            value={status}
            onChange={setStatus}
            options={Object.entries(batchNames).map(([value, label]) => ({
              value,
              label,
            }))}
            style={{ width: 150 }}
          />
          <DatePicker.RangePicker
            value={dates}
            onChange={(values) =>
              setDates(values?.[0] && values[1] ? [values[0], values[1]] : null)
            }
          />
          <Button type="primary" onClick={query}>
            查询
          </Button>
          <Button
            onClick={() => {
              setBatchId('');
              setStatus(undefined);
              setDates(null);
              go(page);
            }}
          >
            重置
          </Button>
        </div>
        <ErrorNotice error={result.error} retry={() => void result.refetch()} />
        {r.scope === 'platform' &&
        r.can('create') &&
        types.data?.items.length === 0 &&
        rows.length === 0 ? (
          <Empty
            description={
              <>
                <strong>尚无可用导入类型</strong>
                <p>平台导入入口保留；类型目录未开放时无法新建批次。</p>
              </>
            }
          />
        ) : (
          <Table<Batch>
            rowKey="id"
            loading={result.isLoading}
            dataSource={rows}
            scroll={{ x: 900 }}
            pagination={{
              current,
              pageSize,
              total: result.data?.total,
              showSizeChanger: false,
              showTotal: (total) => `共 ${total} 条`,
              onChange: (p) => go(page, { ...params, p: String(p) }),
            }}
            columns={[
              {
                title: '批次 / 文件',
                render: (_, item) => (
                  <>
                    <Button
                      type="link"
                      style={{ padding: 0 }}
                      onClick={() => open(item)}
                    >
                      {item.import_type_name}导入
                    </Button>
                    <div style={{ fontSize: 12, color: '#64748b' }}>
                      {item.id}
                      <br />
                      {item.source_artifact?.file_name || '尚未上传文件'}
                    </div>
                  </>
                ),
              },
              { title: '业务类型', dataIndex: 'import_type_name' },
              { title: '目标范围', render: (_, item) => item.scope.name },
              {
                title: '状态',
                dataIndex: 'status',
                render: (value) => <BatchTag value={value} />,
              },
              {
                title: '数据行',
                render: (_, item) =>
                  item.preview ? item.statistics.total_rows : '待确定',
                align: 'right',
              },
              { title: '创建时间', dataIndex: 'created_at', render: time },
              {
                title: '操作',
                render: (_, item) => (
                  <Button type="link" onClick={() => open(item)}>
                    {item.status === 'preview_ready'
                      ? '查看并确认'
                      : '查看结果'}
                  </Button>
                ),
              },
            ]}
          />
        )}
      </Panel>
    </>
  );
}
