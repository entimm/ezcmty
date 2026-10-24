import { Empty } from 'antd';
import { PageHeader, Panel } from '../ui';
import type { FlowPageProps } from '../imports/runtime';
import type { PaymentsRuntime } from './runtime';
import { PaymentOrders } from './PaymentOrders';
import { PaymentDetail } from './PaymentDetail';
import { PaymentConfigurationPage } from './PaymentConfiguration';
import { Reconciliation } from './Reconciliation';
export function PaymentsPage(
  props: FlowPageProps & { runtime: PaymentsRuntime },
) {
  if (
    props.runtime.scope === 'property' &&
    ['payments', 'payment-detail'].includes(props.page) &&
    !props.runtime.communityId
  )
    return (
      <>
        <PageHeader
          title="线上收款"
          description="按当前小区查看支付与资金记录。"
        />
        <Panel>
          <Empty description="请先在上方选择小区；若无可选小区，请联系管理员。" />
        </Panel>
      </>
    );
  if (props.page === 'payment-detail') return <PaymentDetail {...props} />;
  if (props.page === 'payment-configuration')
    return <PaymentConfigurationPage {...props} />;
  if (props.page === 'reconciliation') return <Reconciliation {...props} />;
  return <PaymentOrders {...props} />;
}
