import {
  AuditOutlined,
  FileSearchOutlined,
  HomeOutlined,
  SettingOutlined,
  TeamOutlined,
  WalletOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Link } from '@umijs/max';
import { Card, Col, Row, Statistic, Typography } from 'antd';
import type { ReactNode } from 'react';

import { ReadError } from '../../components/AdminFeedback';
import { useAdminApp } from '../../shared/admin-app-context';
import type { PropertyWorkspaceSummary } from './api';
import { usePropertySession, usePropertyWorkspaceApi } from './hooks';

interface MetricItem {
  key: string;
  title: string;
  description: string;
  path: string;
  permission: string;
  icon: ReactNode;
  value: (summary: PropertyWorkspaceSummary | undefined) => number | null;
  format: (value: number | null) => string;
}

interface WorkspaceItem {
  path: string;
  title: string;
  description: string;
}

interface WorkspaceGroup {
  id: string;
  title: string;
  items: WorkspaceItem[];
}

const formatCount = (value: number | null) =>
  value === null ? '暂无数据' : value.toLocaleString('zh-CN');

const formatCents = (value: number | null) =>
  value === null
    ? '暂无数据'
    : `¥${(value / 100).toLocaleString('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;

const metricItems: MetricItem[] = [
  {
    key: 'pending-house-claims',
    title: '待审核房屋认领',
    description: '处理居民提交的房屋认证申请',
    path: '/property/house-claims',
    permission: 'property.house_claim.read',
    icon: <AuditOutlined />,
    value: (summary) => summary?.pending_house_claims ?? null,
    format: formatCount,
  },
  {
    key: 'monthly-receivable',
    title: '本月应收物业费',
    description: '当前月有效账单的应收金额',
    path: '/property/bills',
    permission: 'property.bill.read',
    icon: <WalletOutlined />,
    value: (summary) => summary?.monthly_receivable_cents ?? null,
    format: formatCents,
  },
  {
    key: 'monthly-settled',
    title: '本月已收物业费',
    description: '当前月有效账单的已收金额',
    path: '/property/payments',
    permission: 'property.payment.read',
    icon: <TeamOutlined />,
    value: (summary) => summary?.monthly_settled_cents ?? null,
    format: formatCents,
  },
  {
    key: 'pending-reconciliation',
    title: '待核对账单',
    description: '尚未解决的收款核对差异',
    path: '/property/payment-reconciliation',
    permission: 'property.payment_reconciliation.read',
    icon: <FileSearchOutlined />,
    value: (summary) => summary?.pending_reconciliation_count ?? null,
    format: formatCount,
  },
];

const workspaceGroups: WorkspaceGroup[] = [
  {
    id: 'billing',
    title: '收费管理',
    items: [
      {
        path: '/property/bills',
        title: '账单管理',
        description: '生成、查询和处理物业费账单',
      },
      {
        path: '/property/payment-configuration',
        title: '收款配置',
        description: '设置收费项目和费率',
      },
      {
        path: '/property/payments',
        title: '收款记录',
        description: '查看已收费用记录',
      },
      {
        path: '/property/payment-reconciliation',
        title: '核对结果',
        description: '核对收款与账单',
      },
    ],
  },
  {
    id: 'housing',
    title: '房屋与业主管理',
    items: [
      {
        path: '/property/communities',
        title: '小区查询',
        description: '查看小区基础信息',
      },
      {
        path: '/property/houses',
        title: '房屋管理',
        description: '维护房屋及业主关系',
      },
      {
        path: '/property/resident-house-bindings',
        title: '居民房屋绑定',
        description: '管理居民与房屋的绑定关系',
      },
      {
        path: '/property/house-claims',
        title: '居民认证审核',
        description: '审核居民提交的认证申请',
      },
    ],
  },
];

export default function HomePage() {
  const { routes, homePath, path } = useAdminApp();
  const { session, status, hasPermission } = usePropertySession();
  const api = usePropertyWorkspaceApi();
  const canReadCompany = hasPermission('property.company.read');
  const summary = useQuery({
    queryKey: ['property-workspace', 'summary'],
    queryFn: api.summary,
    enabled:
      status === 'authenticated' &&
      canReadCompany &&
      metricItems.some((item) => hasPermission(item.permission)),
  });
  const visiblePaths = new Set(
    routes
      .filter(
        (route) =>
          route.path !== homePath &&
          (!route.permission || hasPermission(route.permission)),
      )
      .map((route) => route.path),
  );
  const visibleMetrics = metricItems.filter((item) =>
    hasPermission(item.permission),
  );
  const visibleGroups = workspaceGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => visiblePaths.has(path(item.path))),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <PageContainer title="物业工作台">
      <Card style={{ marginBottom: 24 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          {session?.displayName}，欢迎回来
        </Typography.Title>
        <Typography.Text type="secondary">
          当前账号：{session?.loginName} · 物业管理
        </Typography.Text>
      </Card>

      {visibleMetrics.length > 0 && (
        <section aria-label="运营指标" style={{ marginBottom: 28 }}>
          {summary.isError && (
            <ReadError
              error={summary.error}
              retry={() => void summary.refetch()}
            />
          )}
          <Row gutter={[16, 16]}>
            {visibleMetrics.map((item) => (
              <Col key={item.key} xs={24} sm={12} xl={6}>
                <Link
                  to={path(item.path)}
                  style={{ display: 'block', height: '100%' }}
                  aria-label={`${item.title}，${item.description}`}
                >
                  <Card
                    hoverable
                    loading={summary.fetchStatus === 'fetching'}
                    style={{ height: '100%' }}
                    styles={{ body: { minHeight: 144 } }}
                    title={
                      <span>
                        {item.icon}{' '}
                        <span style={{ marginLeft: 8 }}>{item.title}</span>
                      </span>
                    }
                  >
                    <Statistic
                      value={item.format(item.value(summary.data))}
                      valueStyle={{ fontSize: 26, fontWeight: 600 }}
                    />
                    <Typography.Text type="secondary">
                      {summary.data?.billing_month ?? '当前月'} ·{' '}
                      {item.description}
                    </Typography.Text>
                  </Card>
                </Link>
              </Col>
            ))}
          </Row>
        </section>
      )}

      {visibleGroups.map((group) => (
        <section
          key={group.id}
          aria-labelledby={`${group.id}-title`}
          style={{ marginBottom: 28 }}
        >
          <Typography.Title id={`${group.id}-title`} level={4}>
            {group.title}
          </Typography.Title>
          <Row gutter={[16, 16]}>
            {group.items.map((item) => (
              <Col key={item.path} xs={24} sm={12} xl={6}>
                <Link
                  to={path(item.path)}
                  style={{ display: 'block', height: '100%' }}
                >
                  <Card hoverable style={{ height: '100%' }}>
                    <Card.Meta
                      avatar={
                        group.id === 'billing' ? (
                          <SettingOutlined />
                        ) : (
                          <HomeOutlined />
                        )
                      }
                      title={item.title}
                      description={item.description}
                    />
                  </Card>
                </Link>
              </Col>
            ))}
          </Row>
        </section>
      ))}
    </PageContainer>
  );
}
