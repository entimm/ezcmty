import { Alert, Descriptions } from 'antd';
import { configurationReasons, percent } from './presentation';
import type { PaymentConfiguration } from './types';
export function ConfigurationSummary({ item }: { item: PaymentConfiguration }) {
  return (
    <>
      <Alert
        type={item.ready ? 'success' : 'warning'}
        showIcon
        title={item.ready ? '当前配置可用于新支付' : '当前不可收款'}
        description={item.reasons
          .map((reason) => configurationReasons[reason] || reason)
          .join('；')}
      />
      <Descriptions
        style={{ marginTop: 20 }}
        items={[
          {
            key: 'merchant',
            label: '当前商户',
            children: item.current_binding
              ? `${item.current_binding.merchant_name}（${item.current_binding.merchant_no}）`
              : '未激活',
          },
          {
            key: 'ratio',
            label: '渠道比例上限',
            children:
              item.current_binding?.max_ratio_bps == null
                ? '待核验'
                : percent(item.current_binding.max_ratio_bps),
          },
          {
            key: 'rule',
            label: '当前规则',
            children: item.current_rule
              ? `版本 ${item.current_rule.version_no}，平台服务费 ${item.current_rule.items.map((rule) => percent(rule.rate_bps)).join('、')}`
              : '尚未发布',
          },
          {
            key: 'receiver',
            label: '平台接收关系',
            children: item.reasons.includes('receiver_unready')
              ? '待核验'
              : item.current_binding?.ratio_checked_at
                ? '激活时已核验'
                : '待核验',
          },
        ]}
      />
    </>
  );
}
