import type { BindingStatus, ClaimStatus } from './api';

export const claimLabels: Record<ClaimStatus, string> = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  cancelled: '已撤回',
};
export const bindingLabels: Record<BindingStatus, string> = {
  active: '已绑定',
  released: '居民已解绑',
  revoked: '物业已撤销',
};
export const maskPhone = (value: string) =>
  value.replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2');
export const displayTime = (value: string | null) =>
  value ? new Date(value).toLocaleString() : '—';
