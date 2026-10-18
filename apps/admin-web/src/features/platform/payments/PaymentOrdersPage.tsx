import { useNavigate } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { ReadError } from '../../../components/AdminFeedback';
import { useAdminApp } from '../../../shared/admin-app-context';
import { useListState } from '../../../shared/hooks/use-list-state';
import { PaymentOrdersTable } from '../../../shared/payments/PaymentOrdersTable';
import { usePlatformSession } from '../hooks';
import { usePlatformPaymentsApi } from './hooks';
export default function PaymentOrdersPage() {
  const api = usePlatformPaymentsApi();
  const { status, hasPermission } = usePlatformSession();
  const state = useListState();
  const navigate = useNavigate();
  const { path } = useAdminApp();
  const filters = Object.fromEntries(state.params);
  const query = useQuery({
    queryKey: ['payments', 'orders', filters, state.page, state.pageSize],
    queryFn: () =>
      api.orders({ ...filters, page: state.page, page_size: state.pageSize }),
    enabled:
      status === 'authenticated' && hasPermission('platform.payment.read'),
  });
  return (
    <PageContainer title="支付记录">
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      <PaymentOrdersTable
        companyFilter
        items={query.data?.items || []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total || 0 }}
        filters={filters}
        onFilter={(values) => state.update({ ...values, page: 1 })}
        open={(id) => navigate(path(`/platform/payments/${id}`))}
      />
    </PageContainer>
  );
}
