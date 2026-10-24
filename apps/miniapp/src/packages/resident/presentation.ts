import { formatTime, maskPhone } from '../../core/format';
import type { Binding, Claim, PageResult } from '../../core/types';

export function addressParts(label: string): {
  community: string;
  room: string;
} {
  const parts = label
    .split(/[／/]/)
    .map((part) => part.trim())
    .filter(Boolean);
  return {
    community: parts[0] || '房屋位置',
    room: parts.slice(1).join(' · '),
  };
}
export function bindingView(binding: Binding) {
  const enabled = binding.status === 'active' && binding.effective_enabled;
  return {
    ...binding,
    ...addressParts(binding.house_label_snapshot),
    enabled,
    history: binding.status !== 'active',
    statusText:
      binding.status === 'released'
        ? '已解绑'
        : binding.status === 'revoked'
          ? '物业已撤销'
          : enabled
            ? '服务已开通'
            : '暂不可用',
    tone: enabled ? 'ok' : binding.status === 'active' ? 'wait' : 'gray',
    granted: formatTime(binding.granted_at),
    ended: formatTime(binding.ended_at),
  };
}
export function claimView(claim: Claim) {
  const titles = {
    pending: '等待物业审核',
    approved: '申请已通过',
    rejected: '申请未通过',
    cancelled: '申请已撤回',
  };
  const descriptions = {
    pending: '物业正在核实资料，请耐心等待。',
    approved: '申请已获批准。当前服务以房屋有效授权为准。',
    rejected: '请核对资料后重新提交申请。',
    cancelled: '本次申请已结束，可重新发起认领。',
  };
  return {
    ...claim,
    ...addressParts(claim.house_label_snapshot),
    title: titles[claim.status],
    description: descriptions[claim.status],
    statusText: {
      pending: '待审核',
      approved: '已通过',
      rejected: '未通过',
      cancelled: '已撤回',
    }[claim.status],
    tone: {
      pending: 'wait',
      approved: 'ok',
      rejected: 'bad',
      cancelled: 'gray',
    }[claim.status],
    icon: {
      pending: 'clock-3',
      approved: 'check',
      rejected: 'clipboard-x',
      cancelled: 'undo-2',
    }[claim.status],
    phone: maskPhone(claim.applicant_phone),
    created: formatTime(claim.created_at),
    finished: formatTime(
      claim.status === 'cancelled' ? claim.cancelled_at : claim.reviewed_at,
    ),
  };
}
/** Only publish a complete result; a failed later page never masquerades as empty. */
export async function loadAll<T>(
  load: (page: number) => Promise<PageResult<T>>,
): Promise<T[]> {
  const items: T[] = [];
  let page = 1;
  while (true) {
    const result = await load(page);
    items.push(...result.items);
    if (
      result.page * result.page_size >= result.total ||
      result.items.length === 0
    )
      return items;
    page += 1;
  }
}

export function houseClaimConflict(
  houseId: string,
  bindings: Binding[],
  claims: Claim[],
): string {
  if (
    bindings.some(
      (binding) => binding.house_id === houseId && binding.status === 'active',
    )
  )
    return '此房屋已绑定，请到我的房屋查看。';
  if (
    claims.some(
      (claim) => claim.house_id === houseId && claim.status === 'pending',
    )
  )
    return '此房屋已有待审核申请，请到认领申请查看进度。';
  return '';
}
