import { App, Button } from 'antd';
import { useAdminSession } from '../../../auth/use-admin-session';
import type { PropertyCompany } from '../../../shared/admin-api/property';
import { usePropertyApi, usePropertyOperation } from './hooks';

export function CompanyActions({
  company,
  onEdit,
  operation,
}: {
  company: PropertyCompany;
  onEdit: () => void;
  operation: ReturnType<typeof usePropertyOperation>;
}) {
  const { hasPermission } = useAdminSession();
  const api = usePropertyApi();
  const { modal } = App.useApp();
  if (!hasPermission('property.company.update')) return null;
  return (
    <>
      <Button type="link" disabled={operation.isPending} onClick={onEdit}>
        编辑
      </Button>
      <Button
        type="link"
        danger={company.enabled}
        disabled={operation.isPending}
        onClick={() =>
          modal.confirm({
            title: `${company.enabled ? '停用' : '启用'} ${company.name}？`,
            content: company.enabled
              ? '该公司全部物业账号将无法登录，已有会话立即失效。小区与账号各自的启停状态会保留。'
              : '公司必须至少有一名有效超级管理员。启用后，物业账号需要重新登录。',
            onOk: () =>
              operation
                .mutateAsync({
                  run: () =>
                    api.updateCompany(company.id, {
                      enabled: !company.enabled,
                    }),
                  security: true,
                })
                .then(() => undefined),
          })
        }
      >
        {company.enabled ? '停用' : '启用'}
      </Button>
    </>
  );
}
