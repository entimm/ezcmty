import { useState } from 'react';
import { Link, useParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Descriptions, Space, Spin } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { useAdminApp } from '../../../shared/admin-app-context';
import { usePropertySession } from '../hooks';
import type { Claim } from './api';
import { useHouseClaimsApi } from './hooks';
import { MatchStatus, RecordStatus } from './Parts';
import { displayTime } from './values';
import { DecisionDrawer } from './DecisionDrawer';
import { OwnerPanel } from './OwnerPanel';

export default function ClaimDetailPage() {
  const { claim_id: id = '' } = useParams<{ claim_id: string }>();
  const api = useHouseClaimsApi();
  const { path } = useAdminApp();
  const { status, hasPermission } = usePropertySession();
  const query = useQuery({
    queryKey: ['house-claims', 'detail', id],
    queryFn: () => api.claim(id),
    enabled:
      status === 'authenticated' && hasPermission('property.house_claim.read'),
  });
  const [editing, setEditing] = useState<{
    record: Claim;
    decision: 'approved' | 'rejected';
  }>();
  const claim = query.data;
  return (
    <PageContainer
      title="认领申请详情"
      breadcrumb={{
        items: [
          {
            title: (
              <Link to={path('/property/house-claims')}>房屋认领审核</Link>
            ),
          },
          { title: '申请详情' },
        ],
      }}
      extra={
        claim && (
          <Space>
            <Button
              loading={query.isFetching}
              onClick={() => void query.refetch()}
            >
              刷新状态
            </Button>
            {claim.status === 'pending' &&
              hasPermission('property.house_claim.review') && (
                <>
                  <Button
                    type="primary"
                    disabled={query.isError || query.isFetching}
                    onClick={() =>
                      setEditing({ record: claim, decision: 'approved' })
                    }
                  >
                    通过申请
                  </Button>
                  <Button
                    danger
                    disabled={query.isError || query.isFetching}
                    onClick={() =>
                      setEditing({ record: claim, decision: 'rejected' })
                    }
                  >
                    驳回申请
                  </Button>
                </>
              )}
          </Space>
        )
      }
    >
      {query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : !claim ? (
        <Spin />
      ) : (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <Card title="申请资料" extra={<RecordStatus status={claim.status} />}>
            <Descriptions
              column={{ xs: 1, sm: 2 }}
              items={[
                {
                  key: 'house',
                  label: '房屋位置快照',
                  children: claim.house_label_snapshot,
                  span: 2,
                },
                {
                  key: 'name',
                  label: '申请姓名',
                  children: claim.applicant_name,
                },
                {
                  key: 'phone',
                  label: '申请手机号',
                  children: claim.applicant_phone,
                },
                {
                  key: 'match',
                  label: '历史匹配',
                  children: (
                    <MatchStatus matched={claim.match_status === 'matched'} />
                  ),
                },
                {
                  key: 'time',
                  label: '申请时间',
                  children: displayTime(claim.created_at),
                },
                {
                  key: 'remark',
                  label: '申请备注',
                  children: claim.applicant_remark ?? '—',
                  span: 2,
                },
                {
                  key: 'reason',
                  label: '审核说明',
                  children: claim.review_reason ?? '—',
                  span: 2,
                },
                {
                  key: 'reviewed',
                  label: '审核时间',
                  children: displayTime(claim.reviewed_at),
                },
                {
                  key: 'cancelled',
                  label: '撤回时间',
                  children: displayTime(claim.cancelled_at),
                },
                {
                  key: 'reviewer',
                  label: '审核人 ID',
                  children: claim.reviewed_by_admin_id ?? '—',
                },
                { key: 'id', label: '申请 ID', children: claim.id },
                ...(hasPermission('property.house.read')
                  ? [
                      {
                        key: 'houseLink',
                        label: '房屋资料',
                        children: (
                          <Link
                            to={path(
                              `/property/communities/${claim.community_id}/houses/${claim.house_id}`,
                            )}
                          >
                            查看房屋及档案
                          </Link>
                        ),
                      },
                    ]
                  : []),
                ...(hasPermission('property.resident_house_binding.read')
                  ? [
                      {
                        key: 'bindings',
                        label: '授权记录',
                        children: (
                          <Link
                            to={path(
                              `/property/resident-house-bindings?status=all&house_id=${claim.house_id}`,
                            )}
                          >
                            查看此房屋的绑定
                          </Link>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </Card>
          <OwnerPanel claim={claim} />
        </Space>
      )}
      {editing && (
        <DecisionDrawer
          action={{ kind: 'review', ...editing }}
          done={() => setEditing(undefined)}
        />
      )}
    </PageContainer>
  );
}
