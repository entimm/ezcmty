import { App, Button } from 'antd';
import { usePlatformSession } from '../hooks';
import type { PropertyCompany } from '../../../shared/api/property';
import {
  usePropertyOnboardingApi,
  usePropertyOnboardingOperation,
} from './hooks';

export function CompanyActions({
  company,
  onEdit,
  operation,
}: {
  company: PropertyCompany;
  onEdit: () => void;
  operation: ReturnType<typeof usePropertyOnboardingOperation>;
}) {
  const { hasPermission } = usePlatformSession();
  const api = usePropertyOnboardingApi();
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
                .then(() => undefined)
                .catch(() => {
                  // 页面通过 OperationError 展示失败，关闭确认框以显示提示。
                }),
          })
        }
      >
        {company.enabled ? '停用' : '启用'}
      </Button>
    </>
  );
}
