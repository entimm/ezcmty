import { useNavigate, useParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, Card, Empty } from 'antd';
import { useAdminApp } from '../../../shared/admin-app-context';
import { ReadError } from '../../../components/AdminFeedback';
import { usePropertySession, usePropertyWorkspaceApi } from '../hooks';
import { CommunityPicker } from '../housing/CommunityPicker';
import { BillsTable } from './BillsTable';
import { PendingBillRecovery } from './BillParts';

export default function BillsPage() {
  const { community_id: communityId = '' } = useParams<{
    community_id: string;
  }>();
  const { path } = useAdminApp();
  const navigate = useNavigate();
  const workspace = usePropertyWorkspaceApi();
  const { status, hasPermission } = usePropertySession();
  const community = useQuery({
    queryKey: ['communities', 'detail', communityId],
    queryFn: () => workspace.community(communityId),
    enabled:
      !!communityId &&
      status === 'authenticated' &&
      hasPermission('property.community.read'),
  });
  const location = (id: string) => path(`/property/communities/${id}/bills`);
  return (
    <PageContainer
      title={community.data ? `${community.data.name} · 账单管理` : '账单管理'}
      breadcrumb={{ items: [{ title: '账单管理' }] }}
      content={
        <CommunityPicker
          value={communityId}
          community={community.data}
          onChange={(id) => {
            if (id !== communityId) navigate(location(id));
          }}
          onAutoSelect={(id) => navigate(location(id), { replace: true })}
        />
      }
    >
      <PendingBillRecovery />
      {community.isError && (
        <ReadError
          error={community.error}
          retry={() => void community.refetch()}
        />
      )}
      {community.data?.enabled === false && (
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          title="小区已停用，可查询历史和纠正登记；启用后才能新增账单或收款。"
        />
      )}
      {communityId ? (
        <BillsTable
          key={communityId}
          communityId={communityId}
          enabled={community.data?.enabled !== false}
        />
      ) : (
        <Card>
          <Empty
            description={
              hasPermission('property.community.read')
                ? '请选择小区查看账单'
                : '请联系管理员开通小区查询权限，或从已授权的房屋链接进入'
            }
          />
        </Card>
      )}
    </PageContainer>
  );
}
