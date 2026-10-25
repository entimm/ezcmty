import { Button, Empty, Progress, Tag } from 'antd';
import {
  ApartmentOutlined,
  ArrowRightOutlined,
  AuditOutlined,
  BankOutlined,
  CheckCircleFilled,
  CheckSquareOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  HomeOutlined,
  ImportOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WalletOutlined,
} from '@ant-design/icons';
import type { ComponentType, ReactNode } from 'react';
import { useAdmin } from '../shared/context';
import { useResource } from '../shared/hooks';
import { money, PageHeader, Panel, ReadError } from '../shared/ui';
import type { Page } from '../shared/types';
interface Summary {
  billing_month: string;
  pending_house_claims: number | null;
  monthly_receivable_cents: number | null;
  monthly_settled_cents: number | null;
  pending_reconciliation_count: number | null;
}
interface Metric {
  label: string;
  value: ReactNode;
  note: string;
  icon: ComponentType;
  color: string;
}
export function Dashboard({ companyName }: { companyName?: string }) {
  const { scope, can, request, session, community, communityId, go } =
      useAdmin(),
    property = scope === 'property';
  const summary = useResource(
    ['workspace-summary'],
    () => request<Summary>('/v1/property-workspace/summary'),
    property,
  );
  const platform = useResource(
    ['platform-workspace'],
    async () => {
      const count = async (path: string, permission: string) =>
        can(permission) ? (await request<Page<unknown>>(path)).total : null;
      const [companies, communities, differences, accounts] = await Promise.all(
        [
          count(
            '/v1/property-companies?page=1&page_size=1',
            'platform.onboarding.read',
          ),
          count(
            '/v1/communities?page=1&page_size=1',
            'platform.onboarding.read',
          ),
          count(
            '/v1/payment-reconciliation-discrepancies?page=1&page_size=1&status=open',
            'platform.payment_reconciliation.read',
          ),
          count(
            '/v1/admin-accounts?page=1&page_size=1',
            'platform.system.read',
          ),
        ],
      );
      return { companies, communities, differences, accounts };
    },
    !property,
  );
  const value = summary.data,
    stats = platform.data;
  const unavailable = (v: number | null | undefined) =>
    v == null ? '—' : v.toLocaleString('zh-CN');
  const metrics: Metric[] = property
    ? [
        {
          label: '待审核房屋认领',
          value: unavailable(value?.pending_house_claims),
          note: '本公司全部小区 · 待人工核实',
          icon: CheckSquareOutlined,
          color: 'orange',
        },
        {
          label: '本月应收物业费',
          value:
            value?.monthly_receivable_cents == null
              ? '—'
              : money(value.monthly_receivable_cents / 100),
          note: `${value?.billing_month || '本月'} · 有效账单`,
          icon: FileTextOutlined,
          color: 'blue',
        },
        {
          label: '本月已收物业费',
          value:
            value?.monthly_settled_cents == null
              ? '—'
              : money(value.monthly_settled_cents / 100),
          note: '含线上与线下登记',
          icon: WalletOutlined,
          color: 'green',
        },
        {
          label: '待核对差异',
          value: unavailable(value?.pending_reconciliation_count),
          note: '本公司全部小区 · 对账结果',
          icon: FileSearchOutlined,
          color: 'purple',
        },
      ]
    : [
        {
          label: '已接入物业公司',
          value: unavailable(stats?.companies),
          note: '当前授权管理范围',
          icon: BankOutlined,
          color: 'blue',
        },
        {
          label: '管理小区',
          value: unavailable(stats?.communities),
          note: '含已启用与已停用',
          icon: ApartmentOutlined,
          color: 'purple',
        },
        {
          label: '待核对差异',
          value: unavailable(stats?.differences),
          note: '优先关注资金异常',
          icon: FileSearchOutlined,
          color: 'orange',
        },
        {
          label: '平台管理员',
          value: unavailable(stats?.accounts),
          note: '账号与操作权限独立管理',
          icon: UserOutlined,
          color: 'green',
        },
      ];
  const tasks = property
    ? [
        {
          title: '房屋认领申请',
          note: '核实申请人与业主档案后处理',
          page: 'claims',
          permission: 'property.resident_access.read',
          icon: CheckSquareOutlined,
        },
        {
          title: '物业费账单',
          note: '查看应收、已缴和支付占用状态',
          page: 'bills',
          permission: 'property.bill.read',
          icon: FileTextOutlined,
        },
        {
          title: '线上收款核对',
          note: '查看本公司对账结果，资金处理由平台执行',
          page: 'reconciliation',
          permission: 'property.payment.read',
          icon: FileSearchOutlined,
        },
      ]
    : [
        {
          title: '资金差异核对',
          note: '支付入账、分账和解冻分别确认',
          page: 'reconciliation',
          permission: 'platform.payment_reconciliation.read',
          icon: FileSearchOutlined,
        },
        {
          title: '物业公司接入',
          note: '完善公司资料、开通管理员并配置收款',
          page: 'companies',
          permission: 'platform.onboarding.read',
          icon: BankOutlined,
        },
        {
          title: '权限与操作审计',
          note: '按操作者、结果和业务时间查询',
          page: 'audit',
          permission: 'platform.audit.read',
          icon: AuditOutlined,
        },
      ];
  const quick = property
    ? [
        {
          title: '查看账单',
          page: 'bills',
          permission: 'property.bill.read',
          icon: FileTextOutlined,
        },
        {
          title: '维护房屋',
          page: 'houses',
          permission: 'property.housing.read',
          icon: HomeOutlined,
        },
        {
          title: '审核认领',
          page: 'claims',
          permission: 'property.resident_access.read',
          icon: CheckSquareOutlined,
        },
        {
          title: '批量导入',
          page: 'import-new',
          permission: can('property.housing.manage')
            ? 'property.housing.manage'
            : 'property.bill.manage',
          icon: ImportOutlined,
        },
      ]
    : [
        {
          title: '物业接入',
          page: 'companies',
          permission: 'platform.onboarding.read',
          icon: BankOutlined,
        },
        {
          title: '支付记录',
          page: 'payments',
          permission: 'platform.payment.read',
          icon: WalletOutlined,
        },
        {
          title: '资金对账',
          page: 'reconciliation',
          permission: 'platform.payment_reconciliation.read',
          icon: FileSearchOutlined,
        },
        {
          title: '账号管理',
          page: 'accounts',
          permission: 'platform.system.read',
          icon: UserOutlined,
        },
      ];
  const now = new Date(),
    hour = now.getHours(),
    greeting = hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好';
  const received = value?.monthly_settled_cents,
    receivable = value?.monthly_receivable_cents;
  const ratio =
    received != null && receivable != null && receivable > 0
      ? Math.min(
          100,
          Math.max(0, Math.round((received / receivable) * 1000) / 10),
        )
      : null;
  return (
    <>
      <PageHeader
        title="工作概览"
        description={
          property
            ? '本公司业务总览与当前小区常用入口'
            : '物业接入、资金处理与平台治理，一处掌握'
        }
        extra={
          <span className="date-label">
            {now.toLocaleDateString('zh-CN', {
              year: 'numeric',
              month: 'long',
              day: 'numeric',
              weekday: 'long',
            })}
          </span>
        }
      />
      <div className="welcome-banner">
        <div>
          <div className="eyebrow">
            {property ? '有序工作，从这里开始' : '清晰洞察，高效运营'}
          </div>
          <h2>
            {greeting}，{session.displayName}
            <span className="greeting-dot">。</span>
          </h2>
          <p>
            {property
              ? '收费有依据，业务有进度，让每一次社区服务更从容。'
              : '关注待处理事项，让物业接入与每一笔资金都有迹可循。'}
          </p>
          <span className="welcome-chip">
            <span />
            {property
              ? `${companyName || '本公司'} · 全部小区汇总`
              : '平台授权管理范围 · 所有公司'}
          </span>
        </div>
        <div className="welcome-art" aria-hidden="true">
          {['b1', 'b2', 'b3'].map((b) => (
            <div className={'building ' + b} key={b}>
              {Array.from({ length: b === 'b2' ? 4 : 6 }, (_, i) => (
                <i key={i} />
              ))}
            </div>
          ))}
          <div className="art-orbit" />
          <div className="art-check">
            <CheckCircleFilled />
          </div>
        </div>
      </div>
      {(summary.error || platform.error) && (
        <ReadError
          error={summary.error || platform.error}
          retry={() => void (property ? summary.refetch() : platform.refetch())}
        />
      )}
      <div className="stats-grid">
        {metrics.map(({ label, value, note, icon: Icon, color }) => (
          <div className="metric" key={label}>
            <div className="metric-top">
              <span>{label}</span>
              <span className={'metric-icon ' + color}>
                <Icon />
              </span>
            </div>
            <strong>{value}</strong>
            <small>{note}</small>
          </div>
        ))}
      </div>
      <div className="dashboard-grid">
        <Panel
          title={property ? '当前小区 · 业务待办' : '优先处理'}
          extra={
            <Tag variant="filled">
              {property ? community?.name || '请选择小区' : '平台'}
            </Tag>
          }
        >
          <div className="task-list">
            {tasks
              .filter((item) => can(item.permission))
              .map(({ title, note, page, icon: Icon }) => (
                <button
                  className="task-row"
                  key={page}
                  onClick={() => go(page)}
                >
                  <span className="task-icon">
                    <Icon />
                  </span>
                  <div>
                    <strong>
                      {title}
                      <Tag
                        variant="filled"
                        color={page === 'reconciliation' ? 'orange' : 'blue'}
                      >
                        {page === 'reconciliation'
                          ? '公司范围'
                          : property
                            ? '当前小区'
                            : '授权范围'}
                      </Tag>
                    </strong>
                    <small>{note}</small>
                  </div>
                  <ArrowRightOutlined />
                </button>
              ))}
            {!tasks.some((item) => can(item.permission)) && (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无已授权的业务待办"
              />
            )}
          </div>
        </Panel>
        <Panel
          title="常用操作"
          extra={<ThunderboltOutlined className="muted" />}
        >
          <div className="quick-grid">
            {quick
              .filter((item) => can(item.permission))
              .map(({ title, page, icon: Icon }) => (
                <button key={page} onClick={() => go(page)}>
                  <span>
                    <Icon />
                  </span>
                  <strong>{title}</strong>
                  <ArrowRightOutlined />
                </button>
              ))}
          </div>
          <div className="tip-box">
            <span className="tip-key">⌘ K</span>
            <span>
              搜索菜单与常用操作
              <br />
              <small>快捷跳转，自动继承当前业务上下文</small>
            </span>
          </div>
        </Panel>
      </div>
      <div className="dashboard-grid lower">
        <Panel
          title={property ? '本月收费概况' : '业务处理入口'}
          extra={
            can(property ? 'property.bill.read' : 'platform.payment.read') ? (
              <Button
                type="link"
                onClick={() => go(property ? 'bills' : 'payments')}
              >
                查看{property ? '账单' : '支付记录'} <ArrowRightOutlined />
              </Button>
            ) : undefined
          }
        >
          {property ? (
            <div className="collection-overview">
              <Progress
                type="circle"
                percent={ratio ?? 0}
                size={126}
                strokeColor="var(--brand)"
                strokeWidth={9}
                format={() => (
                  <div>
                    <b>{ratio == null ? '—' : `${ratio}%`}</b>
                    <small>本月收缴率</small>
                  </div>
                )}
              />
              <div>
                <h4>{value?.billing_month || '本月'} · 本公司全部小区</h4>
                <div className="legend">
                  <span>
                    <i style={{ background: 'var(--brand)' }} />
                    已收{' '}
                    <strong>
                      {received == null ? '—' : money(received / 100)}
                    </strong>
                  </span>
                  <span>
                    <i style={{ background: '#dfe5ef' }} />
                    待收{' '}
                    <strong>
                      {received == null || receivable == null
                        ? '—'
                        : money(Math.max(0, receivable - received) / 100)}
                    </strong>
                  </span>
                </div>
                <p className="muted">
                  收缴率按有效账单金额计算；已收包含线上收款与线下登记。
                  <br />
                  无权限或尚无可用统计时显示“—”。
                </p>
              </div>
            </div>
          ) : (
            <div className="business-tip">
              <span className="metric-icon blue">
                <BankOutlined />
              </span>
              <div>
                <h4>物业接入与支付资金分域管理</h4>
                <p>
                  公司资料、管理员与收款配置在公司详情衔接；支付记录和资金对账保留独立处理入口。
                </p>
                {can('platform.onboarding.read') && (
                  <Button type="link" onClick={() => go('companies')}>
                    管理物业公司 <ArrowRightOutlined />
                  </Button>
                )}
              </div>
            </div>
          )}
        </Panel>
        <Panel title="业务提示">
          <div className="business-tip">
            <span className="metric-icon blue">
              <SafetyCertificateOutlined />
            </span>
            <div>
              <h4>
                {property
                  ? '收款结果清楚，资金边界明确'
                  : '异步受理后，继续跟踪真实结果'}
              </h4>
              <p>
                {property
                  ? '线上支付处理中，账单暂不能登记线下收款。分账和解冻异常由平台核实处理。'
                  : '恢复处理只会继续原业务。任务已安排、外部处置已记录，均不代表资金已到账。'}
              </p>
              {can(
                property
                  ? 'property.payment.read'
                  : 'platform.payment_reconciliation.read',
              ) && (
                <Button type="link" onClick={() => go('reconciliation')}>
                  查看{property ? '对账结果' : '资金对账'}{' '}
                  <ArrowRightOutlined />
                </Button>
              )}
              {property && !communityId && (
                <p className="muted">
                  请先在顶部选择小区，再开展房屋与账单业务。
                </p>
              )}
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
