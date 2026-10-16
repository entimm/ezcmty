import { useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Button, Select } from 'antd';
import { useHousingApi } from '../housing/hooks';
import { usePropertySession } from '../hooks';
import { ReadError } from '../../../components/AdminFeedback';

export function HousePicker({
  communityId,
  value,
  onChange,
  enabledOnly = false,
}: {
  communityId: string;
  value?: string;
  onChange?: (value?: string) => void;
  enabledOnly?: boolean;
}) {
  const api = useHousingApi();
  const { hasPermission } = usePropertySession();
  const [search, setSearch] = useState('');
  const query = useInfiniteQuery({
    queryKey: ['houses', 'bill-filter', communityId, search],
    queryFn: ({ pageParam }) =>
      api.houses(communityId, {
        room_no: search,
        page: pageParam,
        page_size: 100,
      }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled: hasPermission('property.house.read'),
  });
  const options = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <>
      <Select
        value={value}
        onChange={onChange}
        allowClear
        placeholder="按房号搜索"
        style={{ minWidth: 220 }}
        showSearch={{ filterOption: false, onSearch: setSearch }}
        loading={query.isFetching}
        options={[
          ...options.map((item) => ({
            value: item.id,
            label: item.display_address,
            disabled: enabledOnly && !item.effective_enabled,
          })),
          ...(value && !options.some((item) => item.id === value)
            ? [{ value, label: value }]
            : []),
        ]}
        popupRender={(menu) => (
          <>
            {menu}
            {query.hasNextPage && (
              <Button
                onClick={() => void query.fetchNextPage()}
                loading={query.isFetchingNextPage}
              >
                加载更多房屋
              </Button>
            )}
          </>
        )}
      />
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
    </>
  );
}
