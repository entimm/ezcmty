import { App, Button } from 'antd';
import type { HousingRecord } from './api';
import { useHousingOperation } from './hooks';

export function StatusAction({
  record,
  label,
  impact,
  operation,
  update,
}: {
  record: HousingRecord;
  label: string;
  impact: string;
  operation: ReturnType<typeof useHousingOperation>;
  update: (enabled: boolean) => Promise<unknown>;
}) {
  const { modal } = App.useApp();
  return (
    <Button
      type="link"
      danger={record.enabled}
      disabled={operation.isPending}
      onClick={() =>
        modal.confirm({
          title: `${record.enabled ? '停用' : '启用'}${label}？`,
          content: record.enabled
            ? impact
            : '实际可用状态还取决于小区及所属上级的启停状态。',
          onOk: () =>
            operation
              .mutateAsync({ run: () => update(!record.enabled) })
              .then(() => undefined),
        })
      }
    >
      {record.enabled ? '停用' : '启用'}
    </Button>
  );
}
