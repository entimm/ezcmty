import type { ReactNode } from 'react';
import { Alert, Button, Progress, Space, Tag } from 'antd';
import { ApiError } from '../request';
import { formatTime as time } from '../datetime';
import type { Task } from './types';
export { time };
export const batchNames: Record<string, string> = {
  draft: '待上传',
  uploading: '接收文件中',
  prechecking: '解析预检中',
  preview_ready: '预检完成',
  executing: '执行中',
  completed: '已完成',
  partial_failed: '部分完成',
  failed: '执行失败',
  blocked: '待核实',
  cancel_requested: '正在取消',
  cancelled: '已取消',
  expired: '已过期',
};
export const rowNames: Record<string, string> = {
  pending: '待处理',
  valid: '通过',
  warning: '警告',
  error: '错误',
  none: '无动作',
  create: '新增',
  skip: '跳过',
  conflict: '拒绝',
  created: '执行成功',
  skipped: '业务跳过',
  failed: '执行失败',
  uncertain: '结果待核实',
  cancelled: '取消未执行',
  excluded: '策略排除',
};
export const phaseNames: Record<string, string> = {
  awaiting_source_file: '等待上传',
  uploading: '接收文件',
  parse_queued: '等待解析',
  parse: '解析文件',
  precheck_queued: '等待预检',
  precheck: '业务预检',
  awaiting_confirmation: '等待确认',
  apply_queued: '等待执行',
  apply: '异步执行',
  recovery_queued: '等待恢复',
  recovery: '核实原任务',
  cancelling: '安全停止',
  finished: '已结束',
  artifact: '生成问题文件',
};
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  if (!error) return null;
  return (
    <Alert
      showIcon
      type="error"
      style={{ marginBottom: 20 }}
      title={error instanceof Error ? error.message : '读取失败，请重试'}
      description={
        error instanceof ApiError && error.requestId
          ? `请求编号：${error.requestId}`
          : undefined
      }
      action={retry && <Button onClick={retry}>重试</Button>}
    />
  );
}
export function BatchTag({ value }: { value: string }) {
  return (
    <Tag
      color={
        value === 'completed'
          ? 'success'
          : ['failed', 'partial_failed'].includes(value)
            ? 'error'
            : value === 'blocked'
              ? 'warning'
              : ['prechecking', 'executing', 'uploading'].includes(value)
                ? 'processing'
                : undefined
      }
    >
      {batchNames[value] || value}
    </Tag>
  );
}
export function Stats({ items }: { items: [string, ReactNode, string?][] }) {
  return (
    <div className="stats-grid">
      {items.map(([label, value, sub]) => (
        <div className="metric" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          {sub && <small>{sub}</small>}
        </div>
      ))}
    </div>
  );
}
export function TaskProgress({ task }: { task: Task | null }) {
  if (!task) return null;
  return (
    <Space orientation="vertical" style={{ width: '100%' }}>
      <strong>
        {phaseNames[task.phase] || task.phase} · 已处理 {task.progress_done} /{' '}
        {task.progress_total ?? '总量待确定'}
      </strong>
      {task.progress_total !== null && task.progress_total > 0 && (
        <Progress
          percent={Math.min(
            100,
            Math.floor((task.progress_done / task.progress_total) * 100),
          )}
          status={task.status === 'paused' ? 'exception' : 'active'}
        />
      )}
      <span style={{ color: '#64748b' }}>
        最近更新：{time(task.updated_at)}
        {task.last_error_code && ` · ${task.last_error_code}`}
      </span>
      {task.status === 'paused' && (
        <Alert
          type="warning"
          showIcon
          title="任务已暂停，请核实原因后恢复原任务"
        />
      )}
    </Space>
  );
}
export function scalar(value: unknown) {
  return value === null || value === undefined
    ? '—'
    : typeof value === 'boolean'
      ? value
        ? '是'
        : '否'
      : String(value);
}
export function cents(value: string | number | bigint | null | undefined) {
  if (value === null || value === undefined) return '待核对';
  try {
    const n = BigInt(value);
    const negative = n < 0n;
    const x = negative ? -n : n;
    return `${negative ? '-' : ''}¥${x / 100n}.${String(x % 100n).padStart(2, '0')}`;
  } catch {
    return '待核对';
  }
}
export const notices: Record<string, string> = {
  property_fee_bills:
    '仅新建账单，创建后立即生效。已有有效账单不覆盖；线上收款不能通过线下操作冲正。',
  houses:
    '请先建立分区、楼栋和单元。仅新增房屋，不携带业主；相同资料跳过，不同资料报冲突。',
  house_owners:
    '仅新增业主登记，不创建房屋、居民账号或房屋授权；相同停用登记不会自动启用。',
};
