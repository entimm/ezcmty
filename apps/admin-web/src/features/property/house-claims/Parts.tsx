import { Tag } from 'antd';
import type { BindingStatus, ClaimStatus } from './api';
import { bindingLabels, claimLabels } from './values';
const colors = {
  pending: 'processing',
  approved: 'success',
  rejected: 'error',
  cancelled: 'default',
  active: 'success',
  released: 'default',
  revoked: 'error',
};
export function RecordStatus({
  status,
}: {
  status: ClaimStatus | BindingStatus;
}) {
  const labels: Record<string, string> = { ...claimLabels, ...bindingLabels };
  return <Tag color={colors[status]}>{labels[status]}</Tag>;
}
export function MatchStatus({ matched }: { matched: boolean }) {
  return (
    <Tag color={matched ? 'green' : 'orange'}>
      {matched ? '申请时匹配' : '申请时未匹配'}
    </Tag>
  );
}
