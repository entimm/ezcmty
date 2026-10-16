import { useState } from 'react';
import { Link, useParams } from '@umijs/max';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Descriptions, Space, Spin } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { useAdminApp } from '../../../shared/admin-app-context';
import { usePropertySession } from '../hooks';
import type { HouseBinding } from './api';
import { useHouseClaimsApi } from './hooks';
import { RecordStatus } from './Parts';
import { displayTime } from './values';
import { DecisionDrawer } from './DecisionDrawer';

export default function BindingDetailPage() {
  const { binding_id: id = '' } = useParams<{ binding_id: string }>();
  const api = useHouseClaimsApi();
  const { path } = useAdminApp();
  const { status, hasPermission } = usePropertySession();
  const query = useQuery({
    queryKey: ['resident-house-bindings', 'detail', id],
    queryFn: () => api.binding(id),
    enabled:
      status === 'authenticated' &&
      hasPermission('property.resident_house_binding.read'),
  });
  const [editing, setEditing] = useState<HouseBinding>();
  const binding = query.data;
  return (
    <PageContainer
      title="居民房屋绑定详情"
      breadcrumb={{
        items: [
          {
            title: (
              <Link to={path('/property/resident-house-bindings')}>
                居民房屋绑定
              </Link>
            ),
          },
          { title: '绑定详情' },
        ],
      }}
      extra={
        binding && (
          <Space>
            <Button
              loading={query.isFetching}
              onClick={() => void query.refetch()}
            >
              刷新状态
            </Button>
            {binding.status === 'active' &&
              hasPermission('property.resident_house_binding.revoke') && (
                <Button
                  danger
                  disabled={query.isError || query.isFetching}
                  onClick={() => setEditing(binding)}
                >
                  撤销绑定
                </Button>
              )}
          </Space>
        )
      }
    >
      {query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : !binding ? (
        <Spin />
      ) : (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          {binding.status === 'active' && !binding.effective_enabled && (
            <Alert
              type="info"
              showIcon
              title="绑定记录仍有效，当前房屋路径或账号已停用，居民暂不可使用该房屋。"
            />
          )}
          <Card
            title="授权记录"
            extra={<RecordStatus status={binding.status} />}
          >
            <Descriptions
              column={{ xs: 1, sm: 2 }}
              items={[
                {
                  key: 'house',
                  label: '房屋位置快照',
                  children: binding.house_label_snapshot,
                  span: 2,
                },
                {
                  key: 'name',
                  label: '申请姓名',
                  children: binding.applicant_name,
                },
                {
                  key: 'phone',
                  label: '申请手机号',
                  children: binding.applicant_phone,
                },
                {
                  key: 'effective',
                  label: '当前权限',
                  children: binding.effective_enabled ? '可使用' : '不可使用',
                },
                {
                  key: 'granted',
                  label: '授予时间',
                  children: displayTime(binding.granted_at),
                },
                {
                  key: 'ended',
                  label: '结束时间',
                  children: displayTime(binding.ended_at),
                },
                {
                  key: 'reason',
                  label: '结束原因',
                  children: binding.end_reason ?? '—',
                },
                { key: 'id', label: '绑定 ID', children: binding.id },
                ...(hasPermission('property.house_claim.read')
                  ? [
                      {
                        key: 'source',
                        label: '来源申请',
                        children: (
                          <Link
                            to={path(
                              `/property/house-claims/${binding.claim_application_id}`,
                            )}
                          >
                            查看原申请
                          </Link>
                        ),
                      },
                    ]
                  : []),
                ...(hasPermission('property.house.read')
                  ? [
                      {
                        key: 'houseLink',
                        label: '房屋资料',
                        children: (
                          <Link
                            to={path(
                              `/property/communities/${binding.community_id}/houses/${binding.house_id}`,
                            )}
                          >
                            查看房屋
                          </Link>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </Card>
        </Space>
      )}
      {editing && (
        <DecisionDrawer
          action={{ kind: 'revoke', record: editing }}
          done={() => setEditing(undefined)}
        />
      )}
    </PageContainer>
  );
}
