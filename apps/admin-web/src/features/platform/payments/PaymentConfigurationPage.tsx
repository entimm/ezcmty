import { useState } from 'react';
import { useParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Pagination,
  Space,
  Spin,
  Table,
} from 'antd';
import { OperationError, ReadError } from '../../../components/AdminFeedback';
import { useListState } from '../../../shared/hooks/use-list-state';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import {
  pendingSnapshot,
  removePending,
  savePending,
} from '../../../shared/pending-requests';
import { ApiError } from '../../../shared/request-client';
import { ConfigurationSummary } from '../../../shared/payments/ConfigurationSummary';
import {
  estimateSharing,
  money,
  parsePercent,
  percent,
} from '../../../shared/payments/presentation';
import { usePlatformSession } from '../hooks';
import type { BindingInput, RuleInput } from './api';
import { usePaymentsOperation, usePlatformPaymentsApi } from './hooks';
type Submission =
  | { kind: 'binding'; key: string; body: BindingInput }
  | { kind: 'rule'; key: string; body: RuleInput };
export default function PaymentConfigurationPage() {
  const { company_id = '' } = useParams<{ company_id: string }>();
  return <ConfigurationEditor key={company_id} companyId={company_id} />;
}
function ConfigurationEditor({ companyId }: { companyId: string }) {
  const api = usePlatformPaymentsApi();
  const { status, hasPermission, session } = usePlatformSession();
  const operation = usePaymentsOperation();
  const dirty = useDirtyForm();
  const { modal, message } = App.useApp();
  const bindingPage = useListState('binding_');
  const rulePage = useListState('rule_');
  const [rate, setRate] = useState('3.00');
  const [editor, setEditor] = useState<Submission['kind']>();
  const pendingKey = `payment-config:${companyId}`;
  const [submission, setSubmission] = useState<Submission | undefined>(() => {
    try {
      return (
        JSON.parse(
          pendingSnapshot('platform_admin', session?.subjectId || ''),
        ) as string[]
      )
        .map((value) => JSON.parse(value) as Submission & { resource?: string })
        .find((value) => value.resource === pendingKey);
    } catch {
      return undefined;
    }
  });
  const enabled =
    status === 'authenticated' && hasPermission('platform.payment_config.read');
  const manage = hasPermission('platform.payment_config.manage');
  const config = useQuery({
    queryKey: ['payment-configuration', companyId],
    queryFn: () => api.configuration(companyId),
    enabled,
  });
  const bindings = useQuery({
    queryKey: [
      'payment-configuration',
      companyId,
      'bindings',
      bindingPage.page,
      bindingPage.pageSize,
    ],
    queryFn: () =>
      api.bindings(companyId, {
        page: bindingPage.page,
        page_size: bindingPage.pageSize,
      }),
    enabled,
  });
  const rules = useQuery({
    queryKey: [
      'payment-configuration',
      companyId,
      'rules',
      rulePage.page,
      rulePage.pageSize,
    ],
    queryFn: () =>
      api.rules(companyId, {
        page: rulePage.page,
        page_size: rulePage.pageSize,
      }),
    enabled,
  });
  const openEditor = (kind: Submission['kind']) => {
    operation.reset();
    setRate('3.00');
    setEditor(kind);
  };
  const closeEditor = () => {
    if (operation.isPending) return;
    dirty.close(() => {
      setEditor(undefined);
      dirty.reset();
      operation.reset();
    });
  };
  const finish = () => {
    if (session) removePending('platform_admin', session.subjectId, pendingKey);
    setSubmission(undefined);
    setEditor(undefined);
    dirty.reset();
  };
  const execute = (value: Submission) => {
    setSubmission(value);
    if (session)
      savePending('platform_admin', session.subjectId, pendingKey, {
        ...value,
        resource: pendingKey,
      });
    operation.mutate(
      {
        run: () =>
          value.kind === 'binding'
            ? api.createBinding(companyId, value.body, value.key)
            : api.createRule(companyId, value.body, value.key),
      },
      {
        onSuccess: () => {
          finish();
          void message.success(
            value.kind === 'binding'
              ? '已创建停用绑定，请核验并激活后发布适用规则'
              : '已发布新版本，仅影响后续新订单',
          );
        },
        onError: (error) => {
          if (
            error instanceof ApiError &&
            error.status >= 400 &&
            error.status < 500
          ) {
            if (session)
              removePending('platform_admin', session.subjectId, pendingKey);
            setSubmission(undefined);
          }
        },
      },
    );
  };
  const activate = (id: string | null) => {
    if (!config.data) return;
    const token = config.data.configuration_token;
    modal.confirm({
      title: id ? '核验并切换收款商户？' : '停止接受新支付？',
      content:
        '仅影响新订单，已有订单继续按原配置处理。提交前将核验商户、接收关系和比例上限；缺少适用规则仍不可收款。',
      onOk: () =>
        operation.mutateAsync({
          run: () => api.activate(companyId, id, token),
        }),
    });
  };
  let example = '请输入有效比例';
  try {
    example = money(estimateSharing(10000, parsePercent(rate)));
  } catch {
    /* Validation is also applied when submitting. */
  }
  const feedback = (
    <>
      <OperationError error={operation.error} />
      {submission && (
        <Alert
          type="warning"
          showIcon
          title="上次创建结果尚需核实，保留原请求与原幂等键"
          description="先刷新核对历史；需要恢复响应时使用原请求重放。"
          action={
            <Button
              disabled={operation.isPending}
              onClick={() => execute(submission)}
            >
              按原请求核实／重放
            </Button>
          }
        />
      )}
    </>
  );
  return (
    <PageContainer
      title="公司收款配置"
      extra={
        <Button
          onClick={() => {
            void config.refetch();
            void bindings.refetch();
            void rules.refetch();
          }}
        >
          刷新核对配置
        </Button>
      }
    >
      {!editor && feedback}
      {config.isPending ? (
        <Spin />
      ) : config.isError ? (
        <ReadError error={config.error} retry={() => void config.refetch()} />
      ) : (
        <Space orientation="vertical" style={{ width: '100%' }}>
          <Card>
            <ConfigurationSummary item={config.data} />
          </Card>
          <Card
            title="商户绑定历史"
            extra={
              manage && (
                <Button
                  type="primary"
                  disabled={operation.isPending || !!submission}
                  onClick={() => openEditor('binding')}
                >
                  创建停用商户绑定
                </Button>
              )
            }
          >
            {bindings.isError && (
              <ReadError
                error={bindings.error}
                retry={() => void bindings.refetch()}
              />
            )}
            <Table
              rowKey="id"
              loading={bindings.isFetching}
              dataSource={bindings.data?.items || []}
              pagination={false}
              columns={[
                { title: '商户', dataIndex: 'merchant_name' },
                { title: '商户号', dataIndex: 'merchant_no' },
                {
                  title: '状态',
                  dataIndex: 'enabled',
                  render: (value: boolean) => (value ? '当前收款商户' : '停用'),
                },
                {
                  title: '比例上限',
                  dataIndex: 'max_ratio_bps',
                  render: (value: number | null) =>
                    value === null ? '待核验' : percent(value),
                },
                ...(manage
                  ? [
                      {
                        title: '操作',
                        key: 'action',
                        render: (
                          _: unknown,
                          row: { id: string; enabled: boolean },
                        ) => (
                          <Button
                            disabled={
                              operation.isPending || !!submission || row.enabled
                            }
                            onClick={() => activate(row.id)}
                          >
                            核验并激活
                          </Button>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
            <Pagination
              {...bindingPage.pagination}
              total={bindings.data?.total || 0}
            />
            {manage && (
              <Button
                disabled={
                  operation.isPending ||
                  !!submission ||
                  !config.data.current_binding
                }
                onClick={() => activate(null)}
              >
                停用新收款
              </Button>
            )}
          </Card>
          <Card
            title="服务费规则版本"
            extra={
              manage && (
                <Button
                  type="primary"
                  disabled={
                    operation.isPending ||
                    !!submission ||
                    !config.data.current_binding
                  }
                  onClick={() => openEditor('rule')}
                >
                  发布完整新规则
                </Button>
              )
            }
          >
            <Alert
              type="info"
              title="按订单金额（扣渠道手续费前）计算，逐接收方四舍五入到分；渠道手续费由物业承担。历史版本不可编辑或删除。"
            />
            {manage && !config.data.current_binding && (
              <Alert
                type="warning"
                showIcon
                title="请先激活收款商户"
                description="在“商户绑定历史”中点击“核验并激活”，成功后即可发布规则；尚无绑定时请先创建。"
              />
            )}
            {rules.isError && (
              <ReadError
                error={rules.error}
                retry={() => void rules.refetch()}
              />
            )}
            <Table
              rowKey="id"
              dataSource={rules.data?.items || []}
              loading={rules.isFetching}
              pagination={false}
              columns={[
                { title: '版本', dataIndex: 'version_no' },
                { title: '发布时间', dataIndex: 'created_at' },
                {
                  title: '平台服务费',
                  key: 'rate',
                  render: (_, row) =>
                    row.items.map((item) => percent(item.rate_bps)).join('、'),
                },
                {
                  title: '接收方',
                  key: 'receiver',
                  render: (_, row) =>
                    row.items.map((item) => item.receiver_name).join('、'),
                },
              ]}
            />
            <Pagination
              {...rulePage.pagination}
              total={rules.data?.total || 0}
            />
          </Card>
          {manage && editor && (
            <Modal
              open
              title={
                editor === 'binding' ? '创建停用商户绑定' : '发布完整新规则'
              }
              onCancel={closeEditor}
              closable={!operation.isPending}
              keyboard={!operation.isPending}
              mask={{ closable: !operation.isPending }}
              footer={null}
              destroyOnHidden
            >
              {feedback}
              {editor === 'binding' ? (
                <Form
                  layout="vertical"
                  disabled={operation.isPending || !!submission}
                  onValuesChange={dirty.changed}
                  onFinish={(values: {
                    merchant_no: string;
                    merchant_name: string;
                  }) =>
                    execute({
                      kind: 'binding',
                      key: crypto.randomUUID(),
                      body: {
                        merchant_no: values.merchant_no.trim(),
                        merchant_name: values.merchant_name.trim(),
                        expected_configuration_token:
                          config.data.configuration_token,
                      },
                    })
                  }
                >
                  <Form.Item
                    name="merchant_no"
                    label="已在线下取得并核实的特约商户号"
                    rules={[{ required: true, whitespace: true, max: 64 }]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="merchant_name"
                    label="商户名称"
                    rules={[{ required: true, whitespace: true, max: 256 }]}
                  >
                    <Input />
                  </Form.Item>
                  <Space>
                    <Button
                      htmlType="submit"
                      type="primary"
                      loading={operation.isPending}
                    >
                      创建停用绑定
                    </Button>
                    <Button
                      disabled={operation.isPending}
                      onClick={closeEditor}
                    >
                      取消
                    </Button>
                  </Space>
                </Form>
              ) : (
                <Form
                  layout="vertical"
                  disabled={
                    operation.isPending ||
                    !!submission ||
                    !config.data.current_binding
                  }
                  initialValues={{ rate: '3.00' }}
                  onValuesChange={(values: { rate?: string }) => {
                    dirty.changed();
                    if (values.rate !== undefined) setRate(values.rate);
                  }}
                  onFinish={(values: { rate: string }) =>
                    modal.confirm({
                      title: '发布新服务费规则？',
                      content:
                        '新规则仅影响后续创建的支付订单，历史支付继续使用原版本。',
                      onOk: () =>
                        execute({
                          kind: 'rule',
                          key: crypto.randomUUID(),
                          body: {
                            expected_configuration_token:
                              config.data.configuration_token,
                            items: [{ rate_bps: parsePercent(values.rate) }],
                          },
                        }),
                    })
                  }
                >
                  <Form.Item
                    label="平台服务费比例（%）"
                    name="rate"
                    rules={[
                      { required: true },
                      {
                        validator: (_, value: string) => {
                          try {
                            parsePercent(value || '');
                            return Promise.resolve();
                          } catch (error) {
                            return Promise.reject(error);
                          }
                        },
                      },
                    ]}
                  >
                    <Input suffix="%" />
                  </Form.Item>
                  <p>
                    示例：订单金额 ¥100.00，平台应分 {example}
                    。实际资金结果以渠道确认为准。
                  </p>
                  <Space>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={operation.isPending}
                    >
                      发布新版本
                    </Button>
                    <Button
                      disabled={operation.isPending}
                      onClick={closeEditor}
                    >
                      取消
                    </Button>
                  </Space>
                </Form>
              )}
            </Modal>
          )}
        </Space>
      )}
    </PageContainer>
  );
}
