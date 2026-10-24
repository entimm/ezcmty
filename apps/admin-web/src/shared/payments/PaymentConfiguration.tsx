import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageHeader, Panel, DetailGrid, Status } from '../ui';
import { useResource } from '../hooks';
import { ApiError } from '../request';
import { hasFormChanges } from '../forms';
import { ErrorNotice, cents, time } from '../imports/presentation';
import type { FlowPageProps } from '../imports/runtime';
import type { PaymentsRuntime } from './runtime';
import type { BindingInput, MerchantBinding, RuleInput } from './types';
import { basisPoints, configurationReasons } from './presentation';
export function PaymentConfigurationPage({
  runtime: r,
  params,
  go,
}: FlowPageProps & { runtime: PaymentsRuntime }) {
  const { message, modal } = App.useApp();
  const setDirty = r.setDirty;
  const [company, setCompany] = useState(params.company || '');
  const [wizard, setWizard] = useState(false);
  const [step, setStep] = useState(0);
  const [binding, setBinding] = useState<MerchantBinding>();
  const [name, setName] = useState('');
  const [merchantNo, setMerchantNo] = useState('');
  const [rate, setRate] = useState<number | null>(null);
  const [sample, setSample] = useState<number | null>(100);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [unknownResult, setUnknownResult] = useState(false);
  const [expectedToken, setExpectedToken] = useState('');
  const [bindingPage, setBindingPage] = useState(1);
  const [rulePage, setRulePage] = useState(1);
  const lock = useRef(false);
  const baseline = useRef<{
    name: string;
    merchantNo: string;
    rate: number | null;
    checked: boolean;
  }>({ name: '', merchantNo: '', rate: null, checked: false });
  const createAttempt = useRef<{ body: BindingInput; key: string } | undefined>(
    undefined,
  );
  const ruleAttempt = useRef<{ body: RuleInput; key: string } | undefined>(
    undefined,
  );
  useEffect(() => {
    setWizard(false);
    setStep(0);
    setBinding(undefined);
    setName('');
    setMerchantNo('');
    setRate(null);
    setChecked(false);
    setError(undefined);
    setUnknownResult(false);
    setBindingPage(1);
    setRulePage(1);
    createAttempt.current = undefined;
    ruleAttempt.current = undefined;
  }, [company]);
  const companies = useResource(
    ['payments', 'companies'],
    () => r.companies!(),
    r.scope === 'platform' && !!r.companies,
  );
  useEffect(() => {
    if (params.company) setCompany(params.company);
  }, [params.company]);
  useEffect(() => {
    if (!company && companies.data?.length) setCompany(companies.data[0].id);
  }, [companies.data, company]);
  const enabled = r.scope === 'property' || !!company;
  const configuration = useResource(
    ['payments', 'configuration', company],
    () => r.api.configuration(company || undefined),
    enabled,
  );
  const bindings = useResource(
    ['payments', 'bindings', company, bindingPage],
    () =>
      r.api.bindings(company || undefined, {
        page: bindingPage,
        page_size: 20,
      }),
    enabled,
  );
  const rules = useResource(
    ['payments', 'rules', company, rulePage],
    () => r.api.rules(company || undefined, { page: rulePage, page_size: 20 }),
    enabled,
  );
  const config = configuration.data;
  const writable = !!r.writes && r.can('payment_config.manage');
  const dirty =
    wizard &&
    hasFormChanges({ name, merchantNo, rate, checked }, baseline.current);
  useEffect(() => {
    setDirty(dirty);
    return () => setDirty(false);
  }, [dirty, setDirty]);
  const refresh = async () => {
    const [current] = await Promise.all([
      configuration.refetch(),
      bindings.refetch(),
      rules.refetch(),
    ]);
    return current.data;
  };
  function begin(existing?: MerchantBinding) {
    if (!config) return;
    createAttempt.current = undefined;
    ruleAttempt.current = undefined;
    setWizard(true);
    setStep(existing ? 1 : 0);
    setBinding(existing);
    baseline.current = {
      name: existing?.merchant_name || '',
      merchantNo: existing?.merchant_no || '',
      rate: null,
      checked: false,
    };
    setName(existing?.merchant_name || '');
    setMerchantNo(existing?.merchant_no || '');
    setRate(null);
    setSample(100);
    setChecked(false);
    setExpectedToken(config.configuration_token);
    setError(undefined);
    setUnknownResult(false);
  }
  function exit() {
    const close = () => {
      setWizard(false);
      setError(undefined);
      setUnknownResult(false);
      r.setDirty(false);
      void refresh();
    };
    if (dirty)
      modal.confirm({
        title: '离开收款配置向导？',
        content: '尚未提交的输入将被清除；已经创建的绑定、激活与规则仍然保留。',
        okText: '离开向导',
        cancelText: '继续配置',
        onOk: close,
      });
    else close();
  }
  async function next() {
    if (lock.current || !r.writes || !config) return;
    if (step === 0 && (!name.trim() || !merchantNo.trim())) {
      message.warning('请填写收款商户名称和商户号');
      return;
    }
    if (step > 0 && !checked) {
      message.warning('请先核对并确认本步骤');
      return;
    }
    if (
      step === 3 &&
      (rate === null ||
        !Number.isFinite(rate) ||
        rate < 0 ||
        rate > 100 ||
        (binding?.max_ratio_bps !== null &&
          binding?.max_ratio_bps !== undefined &&
          Math.round(rate * 100) > binding.max_ratio_bps))
    ) {
      message.warning('服务费比例须符合渠道已核验上限，最多两位小数');
      return;
    }
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      if (step === 0) {
        const body: BindingInput = {
          merchant_no: merchantNo.trim(),
          merchant_name: name.trim(),
          expected_configuration_token: expectedToken,
        };
        createAttempt.current ??= { body, key: crypto.randomUUID() };
        const result = await r.writes.createBinding(
          company,
          createAttempt.current.body,
          createAttempt.current.key,
        );
        setBinding(result);
        setName(result.merchant_name);
        setMerchantNo(result.merchant_no);
        baseline.current = {
          name: result.merchant_name,
          merchantNo: result.merchant_no,
          rate: null,
          checked: false,
        };
        const fresh = await refresh();
        if (!fresh)
          throw new Error('绑定已保存，但最新配置读取失败。请刷新核实后继续。');
        setExpectedToken(fresh.configuration_token);
        setStep(1);
        message.success('停用绑定已创建，尚未开通收款');
      } else if (step === 1) {
        setStep(2);
      } else if (step === 2) {
        const current = await r.writes.activate(
          company,
          binding!.id,
          expectedToken,
        );
        setExpectedToken(current.configuration_token);
        setBinding(current.current_binding || binding);
        setStep(3);
        await refresh();
        message.info(
          current.ready
            ? '商户已激活，可继续发布新规则'
            : '商户已激活，当前收款能力以配置检查结果为准',
        );
      } else {
        const body: RuleInput = {
          expected_configuration_token: expectedToken,
          items: [{ rate_bps: Math.round(rate! * 100) }],
        };
        ruleAttempt.current ??= { body, key: crypto.randomUUID() };
        await r.writes.createRule(
          company,
          ruleAttempt.current.body,
          ruleAttempt.current.key,
        );
        setWizard(false);
        r.setDirty(false);
        await refresh();
        message.success('完整新规则版本已发布，仅对新订单生效');
      }
      setChecked(false);
      setUnknownResult(false);
    } catch (e) {
      setError(e);
      if (
        !(e instanceof ApiError) ||
        e.status === 0 ||
        e.status >= 500 ||
        e.status === 409
      ) {
        setUnknownResult(true);
        await refresh();
      } else {
        if (step === 0) createAttempt.current = undefined;
        if (step === 3) ruleAttempt.current = undefined;
      }
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function deactivate() {
    if (!r.writes || !config) return;
    modal.confirm({
      title: '停用当前收款商户？',
      content: '停用后不能创建新支付。历史订单继续按原冻结配置处理。',
      okText: '确认停用',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        if (lock.current) return;
        lock.current = true;
        setBusy(true);
        try {
          await r.writes!.activate(company, null, config.configuration_token);
          await refresh();
          message.info('已停用新订单收款');
        } catch (e) {
          setError(e);
          await refresh();
        } finally {
          lock.current = false;
          setBusy(false);
        }
      },
    });
  }
  const companyName = companies.data?.find((x) => x.id === company)?.name;
  const formFrozen = busy || (unknownResult && (step === 2 || step === 1));
  return (
    <>
      <PageHeader
        title={r.scope === 'property' ? '收款信息' : '收款配置'}
        back={r.scope === 'platform' ? () => go('companies') : undefined}
        description={
          r.scope === 'property'
            ? '本公司配置只读；商户、费率或收款异常请联系平台处理。'
            : '按绑定、核验、激活、发布规则的顺序管理收款能力。'
        }
        extra={
          !wizard && writable ? (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!config}
              onClick={() => begin()}
            >
              新增绑定与规则
            </Button>
          ) : config ? (
            <Status>{config.ready ? '可收款' : '不可收款'}</Status>
          ) : undefined
        }
      />
      <ErrorNotice error={error} />
      <ErrorNotice
        error={configuration.error}
        retry={() => void configuration.refetch()}
      />
      {wizard ? (
        <>
          <Panel>
            <Steps
              current={step}
              items={[
                { title: '新建商户绑定' },
                { title: '核验接收关系' },
                { title: '激活商户' },
                { title: '发布新规则' },
              ]}
            />
          </Panel>
          <Panel
            title={
              [
                '填写收款商户',
                '核对收款与分账关系',
                '确认激活影响',
                '创建不可变规则版本',
              ][step]
            }
          >
            {unknownResult && (
              <Alert
                style={{ marginBottom: 20 }}
                type="warning"
                showIcon
                title="请求结果待核实或配置已变化"
                description={
                  step === 0 || step === 3
                    ? '输入已固定，可核实历史记录后重放原创建请求；不会自动替换幂等键或并发令牌。'
                    : '请核对最新商户状态，退出后从已保存绑定继续。不会自动换令牌再次激活。'
                }
                action={
                  <Button onClick={() => void refresh()}>刷新配置与历史</Button>
                }
              />
            )}
            <Form
              layout="vertical"
              style={{ maxWidth: 720 }}
              disabled={formFrozen}
            >
              {step === 0 && (
                <>
                  <Form.Item label="收款商户名称" required>
                    <Input
                      value={name}
                      maxLength={256}
                      disabled={busy || !!createAttempt.current}
                      onChange={(event) => setName(event.target.value)}
                    />
                  </Form.Item>
                  <Form.Item
                    label="商户号"
                    required
                    help="填写线下已申请并核实的收款商户号"
                  >
                    <Input
                      value={merchantNo}
                      maxLength={64}
                      disabled={busy || !!createAttempt.current}
                      onChange={(event) => setMerchantNo(event.target.value)}
                    />
                  </Form.Item>
                  <Alert
                    type="info"
                    title="绑定成功不等于可收款，后续仍须核验、激活及发布规则。"
                    style={{ margin: '22px 0' }}
                  />
                </>
              )}
              {step === 1 && (
                <>
                  <DetailGrid
                    items={[
                      ['目标公司', companyName || company],
                      ['新商户', binding?.merchant_name],
                      ['商户号', binding?.merchant_no],
                      [
                        '服务商商户号',
                        binding?.service_provider_merchant_no || '由服务端管理',
                      ],
                      ['渠道比例上限', basisPoints(binding?.max_ratio_bps)],
                      ['最近可信核验', time(binding?.ratio_checked_at)],
                    ]}
                  />
                  <Alert
                    type="warning"
                    showIcon
                    title="请核对线下商户主体和平台接收关系"
                    description="当前页面不虚构渠道核验结果。激活时由服务端校验真实渠道能力、接收关系与比例上限；未满足条件不能开通收款。"
                    style={{ margin: '20px 0' }}
                  />
                  <Checkbox
                    checked={checked}
                    onChange={(event) => setChecked(event.target.checked)}
                  >
                    已核对收款商户及线下接收关系，继续进行服务端核验与激活。
                  </Checkbox>
                </>
              )}
              {step === 2 && (
                <>
                  <DetailGrid
                    items={[
                      ['即将激活', binding?.merchant_name],
                      ['商户号', binding?.merchant_no],
                      [
                        '当前商户',
                        config?.current_binding?.merchant_no || '未激活',
                      ],
                      [
                        '规则状态',
                        config?.current_rule
                          ? `现有规则 v${config.current_rule.version_no}`
                          : '尚未发布规则',
                      ],
                    ]}
                  />
                  <Alert
                    type="warning"
                    showIcon
                    title="切换仅影响新订单，历史订单继续使用原冻结配置。"
                    description="激活将触发服务端可信核验。缺少规则或规则超出新商户上限时，配置仍不可收款。"
                    style={{ margin: '20px 0' }}
                  />
                  <Checkbox
                    checked={checked}
                    onChange={(event) => setChecked(event.target.checked)}
                  >
                    确认激活并继续发布新规则
                  </Checkbox>
                </>
              )}
              {step === 3 && (
                <>
                  <Alert
                    type={config?.ready ? 'info' : 'warning'}
                    showIcon
                    title={
                      config?.ready
                        ? '当前配置可收款，发布规则将影响新订单'
                        : '当前配置不可收款，请发布适用规则并核对检查结果'
                    }
                    description={config?.reasons
                      .map((x) => configurationReasons[x] || x)
                      .join('；')}
                    style={{ marginBottom: 22 }}
                  />
                  <Form.Item
                    label={`平台服务费比例 · 当前最新版本 ${config?.current_rule ? `v${config.current_rule.version_no}` : '尚无'}`}
                    required
                  >
                    <InputNumber
                      value={rate}
                      min={0}
                      max={
                        binding?.max_ratio_bps === null ||
                        binding?.max_ratio_bps === undefined
                          ? 100
                          : binding.max_ratio_bps / 100
                      }
                      precision={2}
                      addonAfter="%"
                      disabled={busy || !!ruleAttempt.current}
                      onChange={setRate}
                      style={{ width: 220 }}
                    />
                  </Form.Item>
                  <Form.Item label="示例订单金额">
                    <InputNumber
                      value={sample}
                      min={0.01}
                      max={100000000}
                      precision={2}
                      addonBefore="¥"
                      onChange={setSample}
                    />
                  </Form.Item>
                  <div
                    style={{
                      padding: 18,
                      borderRadius: 10,
                      background: '#f4f7fc',
                      marginBottom: 20,
                    }}
                  >
                    示例服务费：
                    <strong>
                      {rate === null || sample === null
                        ? '请输入比例与金额'
                        : cents(
                            Number(
                              (BigInt(Math.round(sample * 100)) *
                                BigInt(Math.round(rate * 100)) +
                                5000n) /
                                10000n,
                            ),
                          )}
                    </strong>
                    <p style={{ margin: '6px 0 0', color: '#64748b' }}>
                      金额按分四舍五入；居民应付金额不增加，实际资金结果以可信渠道数据为准。
                    </p>
                  </div>
                  <Checkbox
                    checked={checked}
                    onChange={(event) => setChecked(event.target.checked)}
                  >
                    发布完整新版本，仅对新订单生效；旧规则不可编辑或删除。
                  </Checkbox>
                </>
              )}
              <Space style={{ marginTop: 28 }}>
                <Button disabled={busy} onClick={exit}>
                  退出向导
                </Button>
                <Button
                  type="primary"
                  loading={busy}
                  disabled={
                    !writable ||
                    (step > 0 && !checked) ||
                    (unknownResult && step === 2)
                  }
                  onClick={() => void next()}
                >
                  {
                    [
                      '创建停用绑定',
                      '确认核对并继续',
                      '激活并设置规则',
                      '发布新版本',
                    ][step]
                  }
                </Button>
              </Space>
            </Form>
          </Panel>
        </>
      ) : (
        <>
          {r.scope === 'platform' && (
            <Panel title="目标物业公司">
              <Select
                aria-label="配置所属公司"
                value={company || undefined}
                onChange={(value) => {
                  setCompany(value);
                  setBindingPage(1);
                  setRulePage(1);
                  go('payment-configuration', { company: value });
                }}
                showSearch
                optionFilterProp="label"
                loading={companies.isLoading}
                options={companies.data?.map((x) => ({
                  value: x.id,
                  label: x.name,
                }))}
                style={{ width: 320 }}
              />
              <ErrorNotice error={companies.error} />
            </Panel>
          )}
          {configuration.isLoading ? (
            <Panel>
              <Spin />
            </Panel>
          ) : config ? (
            <Panel
              title="当前收款能力"
              extra={
                <Space>
                  <Status>{config.ready ? '可收款' : '不可收款'}</Status>
                  {writable && config.current_binding && (
                    <Button
                      danger
                      disabled={busy}
                      onClick={() => void deactivate()}
                    >
                      停用新收款
                    </Button>
                  )}
                  <Button
                    icon={<ReloadOutlined />}
                    onClick={() => void refresh()}
                  >
                    刷新
                  </Button>
                </Space>
              }
            >
              <DetailGrid
                items={[
                  [
                    '收款公司',
                    companyName ||
                      config.current_binding?.merchant_name ||
                      '本公司',
                  ],
                  [
                    '当前商户号',
                    config.current_binding?.merchant_no || '未激活',
                  ],
                  [
                    '规则版本',
                    config.current_rule
                      ? `v${config.current_rule.version_no}`
                      : '未发布',
                  ],
                  [
                    '平台服务费',
                    config.current_rule?.items
                      .map((x) => basisPoints(x.rate_bps))
                      .join(' + ') || '未配置',
                  ],
                  [
                    '渠道最大比例',
                    basisPoints(config.current_binding?.max_ratio_bps),
                  ],
                  [
                    '最近可信核验',
                    time(config.current_binding?.ratio_checked_at),
                  ],
                ]}
              />
              {!config.ready && (
                <Alert
                  type="warning"
                  showIcon
                  title="当前暂不可创建新支付"
                  description={config.reasons
                    .map((x) => configurationReasons[x] || x)
                    .join('；')}
                  style={{ marginTop: 20 }}
                />
              )}
              {r.scope === 'property' && (
                <Alert
                  type="info"
                  showIcon
                  title="本公司配置只读，调整商户或费率请联系平台；权限不会扩大公司数据范围。"
                  style={{ marginTop: 20 }}
                />
              )}
            </Panel>
          ) : (
            !configuration.error && (
              <Panel>
                <Empty description="请选择目标物业公司" />
              </Panel>
            )
          )}
          <Panel title="规则历史" extra={<Tag>旧版本不可编辑、不可删除</Tag>}>
            <ErrorNotice
              error={rules.error}
              retry={() => void rules.refetch()}
            />
            <Table
              rowKey="id"
              loading={rules.isLoading}
              dataSource={rules.data?.items}
              pagination={{
                current: rulePage,
                pageSize: 20,
                total: rules.data?.total,
                showSizeChanger: false,
                onChange: setRulePage,
              }}
              columns={[
                {
                  title: '版本',
                  dataIndex: 'version_no',
                  render: (value) => `v${value}`,
                },
                {
                  title: '平台比例',
                  render: (_, v) =>
                    v.items.map((x) => basisPoints(x.rate_bps)).join(' + '),
                },
                {
                  title: '计算口径',
                  render: () => '实际支付金额 × 比例，四舍五入到分',
                },
                { title: '发布日期', dataIndex: 'created_at', render: time },
                {
                  title: '状态',
                  render: (_, v) => (
                    <Status>
                      {v.id === config?.current_rule?.id
                        ? '当前版本'
                        : '历史版本'}
                    </Status>
                  ),
                },
              ]}
            />
          </Panel>
          <Panel title="商户绑定历史">
            <ErrorNotice
              error={bindings.error}
              retry={() => void bindings.refetch()}
            />
            <Table
              rowKey="id"
              loading={bindings.isLoading}
              dataSource={bindings.data?.items}
              pagination={{
                current: bindingPage,
                pageSize: 20,
                total: bindings.data?.total,
                showSizeChanger: false,
                onChange: setBindingPage,
              }}
              columns={[
                { title: '收款商户', dataIndex: 'merchant_name' },
                { title: '商户号', dataIndex: 'merchant_no' },
                { title: '绑定日期', dataIndex: 'created_at', render: time },
                {
                  title: '渠道上限',
                  dataIndex: 'max_ratio_bps',
                  render: basisPoints,
                },
                {
                  title: '状态',
                  dataIndex: 'enabled',
                  render: (value) => (
                    <Status>{value ? '已激活' : '未激活'}</Status>
                  ),
                },
                ...(writable
                  ? [
                      {
                        title: '操作',
                        render: (_: unknown, b: MerchantBinding) => (
                          <Button
                            type="link"
                            onClick={() => {
                              begin(b);
                              if (b.enabled) setStep(3);
                            }}
                          >
                            继续配置
                          </Button>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </Panel>
        </>
      )}
    </>
  );
}
