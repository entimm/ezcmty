import { useState } from 'react';
import { useParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Pagination, Space, Spin } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { useListState } from '../../../shared/hooks/use-list-state';
import { PaymentSummary } from '../../../shared/payments/PaymentSummary';
import { FundsProgress } from '../../../shared/payments/FundsProgress';
import { usePlatformSession } from '../hooks';
import { usePlatformPaymentsApi } from './hooks';
import { RecoveryForm } from './RecoveryForm';
export default function PaymentDetailPage() {
  const { payment_id = '' } = useParams<{ payment_id: string }>();
  const api = usePlatformPaymentsApi();
  const { status, hasPermission } = usePlatformSession();
  const [recovering, setRecovering] = useState(false);
  const sharingPage = useListState('sharing_');
  const unfreezePage = useListState('unfreeze_');
  const allowed = status === 'authenticated';
  const funds = allowed && hasPermission('platform.payment_funds.read');
  const query = useQuery({
    queryKey: ['payments', 'detail', payment_id],
    queryFn: () => api.order(payment_id),
    enabled: allowed && hasPermission('platform.payment.read'),
  });
  const sharing = useQuery({
    queryKey: [
      'payments',
      'sharing',
      payment_id,
      sharingPage.page,
      sharingPage.pageSize,
    ],
    queryFn: () =>
      api.sharing({
        payment_order_id: payment_id,
        page: sharingPage.page,
        page_size: sharingPage.pageSize,
      }),
    enabled: funds,
  });
  const unfreezing = useQuery({
    queryKey: [
      'payments',
      'unfreezing',
      payment_id,
      unfreezePage.page,
      unfreezePage.pageSize,
    ],
    queryFn: () =>
      api.unfreezing({
        payment_order_id: payment_id,
        page: unfreezePage.page,
        page_size: unfreezePage.pageSize,
      }),
    enabled: funds,
  });
  return (
    <PageContainer
      title="支付与资金详情"
      extra={
        <Space>
          <Button
            onClick={() => {
              void query.refetch();
              if (funds) {
                void sharing.refetch();
                void unfreezing.refetch();
              }
            }}
          >
            刷新结果
          </Button>
          {hasPermission('platform.payment_funds.recover') && query.data && (
            <Button onClick={() => setRecovering(true)}>
              重新核实／恢复处理
            </Button>
          )}
        </Space>
      }
    >
      {query.isPending ? (
        <Spin />
      ) : query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <Space orientation="vertical" style={{ width: '100%' }}>
          <PaymentSummary item={query.data} />
          {funds && (
            <>
              {sharing.isError ? (
                <ReadError
                  error={sharing.error}
                  retry={() => void sharing.refetch()}
                />
              ) : null}
              {unfreezing.isError ? (
                <ReadError
                  error={unfreezing.error}
                  retry={() => void unfreezing.refetch()}
                />
              ) : null}
              <Spin spinning={sharing.isFetching || unfreezing.isFetching}>
                <FundsProgress
                  sharing={sharing.data?.items || []}
                  unfreezing={unfreezing.data?.items || []}
                />
              </Spin>
              <span>分账执行分页</span>
              <Pagination
                {...sharingPage.pagination}
                total={sharing.data?.total || 0}
              />
              <span>解冻执行分页</span>
              <Pagination
                {...unfreezePage.pagination}
                total={unfreezing.data?.total || 0}
              />
            </>
          )}
        </Space>
      )}
      {recovering && query.data && (
        <RecoveryForm
          token={query.data.state_token}
          submit={(value) => api.recover(payment_id, value)}
          done={() => setRecovering(false)}
        />
      )}
    </PageContainer>
  );
}
