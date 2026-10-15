import { Tag } from 'antd';

export function HousingStatus({
  enabled,
  effective,
}: {
  enabled: boolean;
  effective?: boolean;
}) {
  return (
    <Tag color={(effective ?? enabled) ? 'green' : undefined}>
      {effective === undefined
        ? enabled
          ? '启用'
          : '停用'
        : effective
          ? '可用'
          : '不可用'}
    </Tag>
  );
}
