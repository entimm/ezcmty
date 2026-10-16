import { BindingStatus, ClaimStatus } from './types';
export const claimLabels: Record<ClaimStatus, string> = {
  pending: '物业审核中',
  approved: '已通过',
  rejected: '未通过',
  cancelled: '已撤回',
};
export const bindingLabels: Record<BindingStatus, string> = {
  active: '已绑定',
  released: '已解绑',
  revoked: '物业已撤销',
};
export const detailUrl = (kind: 'claim' | 'house', id: string) =>
  '/packages/resident/pages/' + kind + '-detail/index?id=' + id;
