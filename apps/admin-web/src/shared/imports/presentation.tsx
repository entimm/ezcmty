import { Alert, Descriptions, Progress, Space, Tag, Typography } from 'antd';
import type { Batch, BatchStatus, BusinessPreview, Task } from './types';
import { businessValue, statusNames, phaseNames, time } from './values';
export function BusinessSummary({
  preview,
  comparison = false,
  includeWarningRows,
  blocked = false,
}: {
  preview: BusinessPreview | null | undefined;
  comparison?: boolean;
  includeWarningRows?: boolean;
  blocked?: boolean;
}) {
  if (!preview?.summary.length) return null;
  return (
    <Space orientation="vertical" style={{ width: '100%' }}>
      <Descriptions
        title="预计新增影响"
        column={1}
        items={preview.summary.map((item) => ({
          key: item.key,
          label: item.label,
          children: comparison ? (
            <>
              <div>
                不含警告行：
                {businessValue(item.without_warning_rows, item.format)}
              </div>
              <div>
                含警告行：{businessValue(item.with_warning_rows, item.format)}
              </div>
            </>
          ) : blocked ? (
            '当前策略有错误行，请先调整执行策略'
          ) : includeWarningRows === undefined ? (
            '请先选择是否执行警告行'
          ) : (
            businessValue(
              includeWarningRows
                ? item.with_warning_rows
                : item.without_warning_rows,
              item.format,
            )
          ),
        }))}
      />
      <Typography.Text type="secondary">
        合计由服务端按完整预览计算，排除跳过、错误和非新增行。此处为预计新增影响，实际结果以已提交行记录为准。
      </Typography.Text>
    </Space>
  );
}
export function BatchStatusTag({ status }: { status: BatchStatus }) {
  return (
    <Tag
      color={
        status === 'blocked'
          ? 'warning'
          : status === 'completed'
            ? 'success'
            : undefined
      }
    >
      {statusNames[status]}
    </Tag>
  );
}
export function TaskProgress({ task }: { task: Task | null }) {
  if (!task) return null;
  return (
    <Space orientation="vertical" style={{ width: '100%' }}>
      <Typography.Text>
        {phaseNames[task.phase]} · 已处理 {task.progress_done} /{' '}
        {task.progress_total === null ? '总行数未知' : task.progress_total}
      </Typography.Text>
      {task.progress_total !== null && task.progress_total > 0 && (
        <Progress
          percent={Math.min(
            100,
            Math.floor((task.progress_done / task.progress_total) * 100),
          )}
          status={task.status === 'paused' ? 'exception' : 'active'}
        />
      )}
      <Typography.Text type="secondary">
        最近更新：{time(task.updated_at)}
        {task.last_error_code ? ` · ${task.last_error_code}` : ''}
      </Typography.Text>
      {task.status === 'paused' && (
        <Alert
          type="warning"
          title="任务已暂停，需要核实阻断原因后恢复原任务"
        />
      )}
    </Space>
  );
}
export function Statistics({ batch }: { batch: Batch }) {
  const p = batch.statistics.preview,
    e = batch.statistics.execution;
  return (
    <Space orientation="vertical" style={{ width: '100%' }}>
      <Descriptions
        title="预览计划与问题"
        size="small"
        bordered
        items={[
          {
            key: 'total',
            label: '总行数',
            children:
              batch.source_artifact && batch.preview
                ? batch.statistics.total_rows
                : '未知',
          },
          ...Object.entries({
            新增: p.create_rows,
            更新: p.update_rows,
            跳过: p.skip_rows,
            警告: p.warning_rows,
            错误: p.error_rows,
          }).map(([label, children]) => ({ key: label, label, children })),
        ]}
      />
      <Typography.Text type="secondary">
        创建模式，不会更新已有数据。计划动作与问题统计可以重叠，不能相加。
      </Typography.Text>
      <Descriptions
        title="本批次实际结果"
        size="small"
        bordered
        items={Object.entries({
          创建成功: e.created_rows,
          更新成功: e.updated_rows,
          业务跳过: e.skipped_rows,
          执行失败: e.failed_rows,
          待核实: e.uncertain_rows,
          策略排除: e.excluded_rows,
          取消未执行: e.cancelled_rows,
          已处理: e.processed_rows,
          可安全重试: e.retryable_failed_rows,
        }).map(([label, children]) => ({ key: label, label, children }))}
      />
      {e.uncertain_rows > 0 && (
        <Alert
          type="warning"
          showIcon
          title="存在待核实结果，请核实并恢复原任务"
          description="未知结果不计为失败，不能通过失败行重跑创建新操作。"
        />
      )}
    </Space>
  );
}
