import { useEffect, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Button, Empty, Select, Space, Spin } from 'antd';
import type { Community } from '../../../shared/api/property';
import { ReadError } from '../../../components/AdminFeedback';
import { usePropertySession, usePropertyWorkspaceApi } from '../hooks';

export function CommunityPicker({
  value,
  community,
  onChange,
  onAutoSelect,
}: {
  value?: string;
  community?: Community;
  onChange: (value: string) => void;
  onAutoSelect: (value: string) => void;
}) {
  const api = usePropertyWorkspaceApi();
  const { status, hasPermission } = usePropertySession();
  const [search, setSearch] = useState('');
  const permitted =
    status === 'authenticated' && hasPermission('property.community.read');
  const query = useInfiniteQuery({
    queryKey: ['communities', 'options', search],
    queryFn: ({ pageParam }) =>
      api.communities({ name: search, page: pageParam, page_size: 100 }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled: permitted,
  });
  const firstPage = query.data?.pages[0];
  const singleCommunityId =
    firstPage?.total === 1 && firstPage.items.length === 1
      ? firstPage.items[0].id
      : undefined;
  useEffect(() => {
    if (
      permitted &&
      !value &&
      !search &&
      query.isSuccess &&
      !query.isFetching &&
      singleCommunityId
    )
      onAutoSelect(singleCommunityId);
  }, [
    permitted,
    value,
    search,
    query.isSuccess,
    query.isFetching,
    singleCommunityId,
    onAutoSelect,
  ]);
  if (!permitted) return null;
  const choices = new Map(
    query.data?.pages
      .flatMap((page) => page.items)
      .map((item) => [item.id, item]) ?? [],
  );
  if (community) choices.set(community.id, community);
  return (
    <Space wrap>
      <span>当前小区</span>
      <Select
        aria-label="当前小区"
        value={value || undefined}
        onChange={onChange}
        placeholder="请选择小区"
        style={{ width: 280, maxWidth: '100%' }}
        showSearch={{ filterOption: false, onSearch: setSearch }}
        loading={query.isFetching}
        options={[...choices.values()].map((item) => ({
          value: item.id,
          label: `${item.name}（${item.code}）${item.enabled ? '' : ' · 停用'}`,
        }))}
        notFoundContent={
          query.isPending ? (
            <Spin size="small" />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={search ? '没有匹配的小区' : '暂无可选小区'}
            />
          )
        }
        popupRender={(menu) => (
          <>
            {query.isError && (
              <ReadError
                error={query.error}
                retry={() => void query.refetch()}
              />
            )}
            {menu}
            {query.hasNextPage && (
              <Space style={{ padding: 8 }}>
                <Button
                  loading={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}
                >
                  加载更多小区
                </Button>
              </Space>
            )}
          </>
        )}
      />
    </Space>
  );
}
