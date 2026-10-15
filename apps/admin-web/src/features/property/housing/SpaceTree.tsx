import { useEffect, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Button, Empty, Space, Spin, Tag } from 'antd';
import { ReadError } from '../../../components/AdminFeedback';
import { usePropertySession } from '../hooks';
import { useHousingApi } from './hooks';
import type { SpaceNode } from './api';

const labels = { phase: '分区', building: '楼栋', unit: '单元' };

export function SpaceBranch({
  communityId,
  parentId,
  selectedId,
  restorePath = [],
  onSelect,
  houseLocation = false,
}: {
  communityId: string;
  parentId?: string;
  selectedId?: string;
  restorePath?: string[];
  onSelect: (node: SpaceNode) => void;
  houseLocation?: boolean;
}) {
  const api = useHousingApi();
  const { status, hasPermission } = usePropertySession();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const query = useInfiniteQuery({
    queryKey: ['spaces', 'children', communityId, parentId],
    queryFn: ({ pageParam }) =>
      api.nodes(communityId, {
        parent_id: parentId,
        page: pageParam,
        page_size: 20,
      }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled: status === 'authenticated' && hasPermission('property.space.read'),
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const parentIndex = parentId ? restorePath.indexOf(parentId) : -1;
  const target = !parentId
    ? restorePath[0]
    : parentIndex >= 0
      ? restorePath[parentIndex + 1]
      : undefined;
  const needsRestore = !!target && !items.some((node) => node.id === target);
  const { fetchNextPage, hasNextPage, isFetching } = query;
  useEffect(() => {
    if (needsRestore && hasNextPage && !isFetching && !query.isError)
      void fetchNextPage();
  }, [needsRestore, hasNextPage, isFetching, fetchNextPage, query.isError]);
  return (
    <>
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      {query.isPending && <Spin size="small" />}
      {query.isSuccess && items.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无空间节点"
        />
      )}
      <ul
        role="group"
        style={{ paddingLeft: parentId ? 18 : 0, listStyle: 'none', margin: 0 }}
      >
        {items.map((node) => {
          const open = expanded[node.id] ?? restorePath.includes(node.id);
          const selectable =
            !houseLocation ||
            (node.node_type !== 'phase' && node.effective_enabled);
          return (
            <li
              key={node.id}
              role="treeitem"
              aria-selected={selectedId === node.id}
              aria-expanded={node.has_children ? open : undefined}
            >
              <Space size={0} wrap>
                {node.has_children && (
                  <Button
                    size="small"
                    type="text"
                    aria-label={`${open ? '收起' : '展开'}${node.name}`}
                    onClick={() =>
                      setExpanded((old) => ({ ...old, [node.id]: !open }))
                    }
                  >
                    {open ? '−' : '+'}
                  </Button>
                )}
                <Button
                  type={selectedId === node.id ? 'primary' : 'text'}
                  disabled={!selectable}
                  onClick={() => onSelect(node)}
                >
                  {node.name}
                </Button>
                <Tag>{labels[node.node_type]}</Tag>
                {!node.effective_enabled && <Tag>不可用</Tag>}
              </Space>
              {node.has_children && open && (
                <SpaceBranch
                  communityId={communityId}
                  parentId={node.id}
                  selectedId={selectedId}
                  restorePath={restorePath}
                  onSelect={onSelect}
                  houseLocation={houseLocation}
                />
              )}
            </li>
          );
        })}
      </ul>
      {query.hasNextPage && (
        <Button
          type="link"
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          加载更多空间
        </Button>
      )}
    </>
  );
}

export function LocationPicker({
  communityId,
  value,
  onChange,
}: {
  communityId: string;
  value?: string;
  onChange?: (value: string) => void;
}) {
  const api = useHousingApi();
  const { status, hasPermission } = usePropertySession();
  const detail = useQuery({
    queryKey: ['spaces', 'detail', communityId, value],
    queryFn: () => api.node(communityId, value!),
    enabled:
      !!value &&
      status === 'authenticated' &&
      hasPermission('property.space.read'),
  });
  const node = detail.data;
  return (
    <div>
      <p>
        {node
          ? [...node.ancestors.map((part) => part.name), node.name].join('／')
          : '请选择楼栋或单元'}
      </p>
      {detail.isError && (
        <ReadError error={detail.error} retry={() => void detail.refetch()} />
      )}
      <div
        role="tree"
        aria-label="房屋所属空间"
        style={{
          maxHeight: 260,
          overflow: 'auto',
          border: '1px solid #ddd',
          padding: 8,
        }}
      >
        <SpaceBranch
          communityId={communityId}
          selectedId={value}
          restorePath={
            node ? [...node.ancestors.map((part) => part.id), node.id] : []
          }
          onSelect={(item) => onChange?.(item.id)}
          houseLocation
        />
      </div>
    </div>
  );
}
