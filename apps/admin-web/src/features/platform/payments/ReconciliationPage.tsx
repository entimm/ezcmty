import { useState } from 'react';
import { Link } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Drawer, Space, Spin } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { useAdminApp } from '../../../shared/admin-app-context';
import { useListState } from '../../../shared/hooks/use-list-state';
import { ReconciliationTables } from '../../../shared/payments/ReconciliationTables';
import {
  DiscrepancySummary,
  ReconciliationSummary,
} from '../../../shared/payments/DiscrepancySummary';
import { usePlatformSession } from '../hooks';
import { usePlatformPaymentsApi } from './hooks';
import { RecoveryForm } from './RecoveryForm';
import { ExternalResolutionForm } from './ExternalResolutionForm';
export default function ReconciliationPage() {
  const api = usePlatformPaymentsApi();
  const { status, hasPermission } = usePlatformSession();
  const { path } = useAdminApp();
  const state = useListState();
  const runPage = useListState('run_');
  const diffPage = useListState('difference_');
  const [action, setAction] = useState<
    'recover' | 'recheck' | 'external' | undefined
  >();
  const filters = Object.fromEntries(
    [...state.params].filter(([key]) =>
      [
        'property_company_id',
        'business_date_from',
        'business_date_through',
        'statement_type',
      ].includes(key),
    ),
  );
  const enabled =
    status === 'authenticated' &&
    hasPermission('platform.payment_reconciliation.read');
  const runId = state.params.get('run') || '';
  const differenceId = state.params.get('difference') || '';
  const runs = useQuery({
    queryKey: [
      'reconciliation',
      'runs',
      filters,
      runPage.page,
      runPage.pageSize,
    ],
    queryFn: () =>
      api.runs({ ...filters, page: runPage.page, page_size: runPage.pageSize }),
    enabled,
  });
  const differences = useQuery({
    queryKey: [
      'reconciliation',
      'differences',
      filters,
      diffPage.page,
      diffPage.pageSize,
    ],
    queryFn: () =>
      api.discrepancies({
        ...filters,
        page: diffPage.page,
        page_size: diffPage.pageSize,
      }),
    enabled,
  });
  const run = useQuery({
    queryKey: ['reconciliation', 'run', runId],
    queryFn: () => api.run(runId),
    enabled: enabled && !!runId,
  });
  const difference = useQuery({
    queryKey: ['reconciliation', 'difference', differenceId],
    queryFn: () => api.discrepancy(differenceId),
    enabled: enabled && !!differenceId,
  });
  const verify = () => {
    void difference.refetch();
    void differences.refetch();
  };
  return (
    <PageContainer title="资金核对工作台">
      {runs.isError && (
        <ReadError error={runs.error} retry={() => void runs.refetch()} />
      )}{' '}
      {differences.isError && (
        <ReadError
          error={differences.error}
          retry={() => void differences.refetch()}
        />
      )}
      <ReconciliationTables
        companyFilter
        runs={runs.data?.items || []}
        differences={differences.data?.items || []}
        loadingRuns={runs.isFetching}
        loadingDifferences={differences.isFetching}
        runPagination={{ ...runPage.pagination, total: runs.data?.total || 0 }}
        differencePagination={{
          ...diffPage.pagination,
          total: differences.data?.total || 0,
        }}
        filters={filters}
        onFilter={(values) =>
          state.update({ ...values, run_page: 1, difference_page: 1 })
        }
        openRun={(id) => state.update({ run: id, difference: undefined })}
        openDifference={(id) =>
          state.update({ difference: id, run: undefined })
        }
      />
      <Drawer
        open={!!runId}
        title="核对批次详情"
        size={660}
        onClose={() => {
          state.update({ run: undefined });
          setAction(undefined);
        }}
      >
        {run.isPending ? (
          <Spin />
        ) : run.isError ? (
          <ReadError error={run.error} retry={() => void run.refetch()} />
        ) : (
          <>
            <ReconciliationSummary item={run.data} />
            {hasPermission('platform.payment_reconciliation.recheck') && (
              <Button
                disabled={run.data.status === 'running'}
                onClick={() => setAction('recheck')}
              >
                按证据重新核对
              </Button>
            )}
          </>
        )}
      </Drawer>
      <Drawer
        open={!!differenceId}
        title="差异详情与判定依据"
        size={720}
        onClose={() => {
          state.update({ difference: undefined });
          setAction(undefined);
        }}
      >
        {difference.isPending ? (
          <Spin />
        ) : difference.isError ? (
          <ReadError
            error={difference.error}
            retry={() => void difference.refetch()}
          />
        ) : (
          <Space orientation="vertical" style={{ width: '100%' }}>
            <DiscrepancySummary item={difference.data} />
            <Button onClick={verify}>重新读取当前差异</Button>
            <Button
              onClick={() =>
                state.update({
                  run: difference.data.reconciliation_run_id,
                  difference: undefined,
                })
              }
            >
              查看来源批次
            </Button>
            {difference.data.payment_order_id &&
              hasPermission('platform.payment.read') && (
                <Link
                  to={path(
                    `/platform/payments/${difference.data.payment_order_id}`,
                  )}
                >
                  查看关联支付
                </Link>
              )}
            {hasPermission('admin.audit.read') && (
              <Link to={path('/platform/system/audit-logs')}>
                查看管理员审计
              </Link>
            )}
            {hasPermission('platform.payment_funds.recover') && (
              <Space>
                <Button
                  disabled={
                    difference.data.status === 'resolved' ||
                    !difference.data.payment_order_id
                  }
                  onClick={() => setAction('recover')}
                >
                  恢复原业务
                </Button>
                <Button
                  disabled={difference.data.status === 'resolved'}
                  onClick={() => setAction('external')}
                >
                  记录外部处置
                </Button>
              </Space>
            )}
          </Space>
        )}
      </Drawer>
      {action === 'recheck' && run.data && (
        <RecoveryForm
          token={run.data.state_token}
          submit={(value) => api.recheck(run.data.id, value)}
          done={() => setAction(undefined)}
        />
      )}
      {action === 'recover' && difference.data && (
        <RecoveryForm
          token={difference.data.state_token}
          submit={(value) => api.recoverDifference(difference.data.id, value)}
          done={() => setAction(undefined)}
        />
      )}
      {action === 'external' && difference.data && (
        <ExternalResolutionForm
          token={difference.data.state_token}
          submit={(value) => api.externalResolution(difference.data.id, value)}
          verify={verify}
          done={() => setAction(undefined)}
        />
      )}
    </PageContainer>
  );
}
