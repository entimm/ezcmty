import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Drawer, Spin } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { useListState } from '../../../shared/hooks/use-list-state';
import { ReconciliationTables } from '../../../shared/payments/ReconciliationTables';
import {
  DiscrepancySummary,
  ReconciliationSummary,
} from '../../../shared/payments/DiscrepancySummary';
import { usePropertySession } from '../hooks';
import { usePropertyPaymentsApi } from './hooks';
export default function ReconciliationPage() {
  const api = usePropertyPaymentsApi();
  const { status, hasPermission } = usePropertySession();
  const state = useListState();
  const runPage = useListState('run_');
  const diffPage = useListState('difference_');
  const filters = Object.fromEntries(
    [...state.params].filter(
      ([key, value]) =>
        [
          'business_date_from',
          'business_date_through',
          'statement_type',
        ].includes(key) && value !== 'platform_fundflow',
    ),
  );
  const enabled =
    status === 'authenticated' &&
    hasPermission('property.payment_reconciliation.read');
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
  return (
    <PageContainer title="本公司资金核对结果">
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
        title="本公司核对批次"
        size={660}
        onClose={() => state.update({ run: undefined })}
      >
        {run.isPending ? (
          <Spin />
        ) : run.isError ? (
          <ReadError error={run.error} retry={() => void run.refetch()} />
        ) : (
          <ReconciliationSummary item={run.data} />
        )}
      </Drawer>
      <Drawer
        open={!!differenceId}
        title="本公司差异"
        size={660}
        onClose={() => state.update({ difference: undefined })}
      >
        {difference.isPending ? (
          <Spin />
        ) : difference.isError ? (
          <ReadError
            error={difference.error}
            retry={() => void difference.refetch()}
          />
        ) : (
          <DiscrepancySummary item={difference.data} />
        )}
      </Drawer>
    </PageContainer>
  );
}
