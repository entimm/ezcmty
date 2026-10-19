import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Pagination, Space, Spin, Table } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { useListState } from '../../../shared/hooks/use-list-state';
import { ConfigurationSummary } from '../../../shared/payments/ConfigurationSummary';
import { percent } from '../../../shared/payments/presentation';
import { usePropertySession } from '../hooks';
import { usePropertyPaymentsApi } from './hooks';
export default function PaymentConfigurationPage() {
  const api = usePropertyPaymentsApi();
  const { status, hasPermission } = usePropertySession();
  const bindingPage = useListState('binding_');
  const rulePage = useListState('rule_');
  const enabled =
    status === 'authenticated' && hasPermission('property.payment_config.read');
  const config = useQuery({
    queryKey: ['payment-configuration'],
    queryFn: api.configuration,
    enabled,
  });
  const bindings = useQuery({
    queryKey: [
      'payment-configuration',
      'bindings',
      bindingPage.page,
      bindingPage.pageSize,
    ],
    queryFn: () =>
      api.bindings({ page: bindingPage.page, page_size: bindingPage.pageSize }),
    enabled,
  });
  const rules = useQuery({
    queryKey: [
      'payment-configuration',
      'rules',
      rulePage.page,
      rulePage.pageSize,
    ],
    queryFn: () =>
      api.rules({ page: rulePage.page, page_size: rulePage.pageSize }),
    enabled,
  });
  return (
    <PageContainer title="本公司收款配置">
      {config.isPending ? (
        <Spin />
      ) : config.isError ? (
        <ReadError error={config.error} retry={() => void config.refetch()} />
      ) : (
        <Space orientation="vertical" style={{ width: '100%' }}>
          <Card>
            <ConfigurationSummary item={config.data} />
            <Alert
              type="info"
              title="收款配置由平台维护。如有异常，请联系平台。"
            />
          </Card>
          <Card title="收款商户">
            {bindings.isError && (
              <ReadError
                error={bindings.error}
                retry={() => void bindings.refetch()}
              />
            )}
            <Table
              rowKey="id"
              pagination={false}
              loading={bindings.isFetching}
              dataSource={bindings.data?.items || []}
              columns={[
                { title: '商户名称', dataIndex: 'merchant_name' },
                { title: '商户号', dataIndex: 'merchant_no' },
                {
                  title: '状态',
                  dataIndex: 'enabled',
                  render: (value: boolean) => (value ? '当前启用' : '历史停用'),
                },
              ]}
            />
            <Pagination
              {...bindingPage.pagination}
              total={bindings.data?.total || 0}
            />
          </Card>
          <Card title="服务费规则版本">
            {rules.isError && (
              <ReadError
                error={rules.error}
                retry={() => void rules.refetch()}
              />
            )}
            <Table
              rowKey="id"
              pagination={false}
              loading={rules.isFetching}
              dataSource={rules.data?.items || []}
              columns={[
                { title: '版本', dataIndex: 'version_no' },
                {
                  title: '平台服务费',
                  key: 'rate',
                  render: (_, row) =>
                    row.items.map((item) => percent(item.rate_bps)).join('、'),
                },
                { title: '发布时间', dataIndex: 'created_at' },
              ]}
            />
            <Pagination
              {...rulePage.pagination}
              total={rules.data?.total || 0}
            />
          </Card>
        </Space>
      )}
    </PageContainer>
  );
}
