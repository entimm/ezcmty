import type { BatchStatus } from './types';
export const statusNames: Record<BatchStatus, string> = {
  draft: '等待上传',
  uploading: '文件上传中',
  prechecking: '解析与预检中',
  preview_ready: '等待确认',
  executing: '执行中',
  completed: '已完成',
  partial_failed: '部分失败',
  failed: '失败',
  blocked: '需要人工处理',
  cancel_requested: '等待安全停止',
  cancelled: '已安全停止',
  expired: '已过期',
};
export const phaseNames: Record<string, string> = {
  awaiting_source_file: '等待源文件',
  uploading: '文件传输',
  parse_queued: '解析排队',
  parse: '文件解析',
  precheck_queued: '预检排队',
  precheck: '规范化与业务预检',
  awaiting_confirmation: '等待显式确认',
  apply_queued: '执行排队',
  apply: '执行',
  recovery_queued: '恢复排队',
  recovery: '核实原任务',
  cancelling: '安全停止中',
  finished: '已结束',
  artifact: '错误文件生成',
};
export const resultNames: Record<string, string> = {
  pending: '尚未执行',
  created: '创建成功',
  skipped: '业务跳过',
  failed: '执行失败',
  uncertain: '待核实',
  cancelled: '取消未执行',
  excluded: '策略排除',
};
export const actionNames: Record<string, string> = {
  none: '无动作',
  create: '新增',
  skip: '跳过',
  conflict: '拒绝',
};
export const fileStatusNames = {
  not_generated: '待生成',
  queued: '生成排队',
  generating: '生成中',
  ready: '可下载',
  stale: '已失效，需重新生成',
  failed: '生成失败',
  expired: '已过期',
};
export const time = (value: string | null) =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
export const cell = (value: unknown) =>
  value === null || value === undefined ? '—' : String(value);
