import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Button, Input, Select, Space } from 'antd';
import { useState } from 'react';
import { usePlatformSession } from '../hooks';
import { ReadError } from '../../../components/AdminFeedback';
import { usePropertyOnboardingApi } from './hooks';

export function CompanyPicker({
  value,
  onChange,
}: {
  value?: string;
  onChange?: (value?: string) => void;
}) {
  const api = usePropertyOnboardingApi();
  const { status, hasPermission } = usePlatformSession();
  const [search, setSearch] = useState('');
  const permitted =
    status === 'authenticated' && hasPermission('property.company.read');
  const query = useInfiniteQuery({
    queryKey: ['property-companies', 'options', search],
    queryFn: ({ pageParam }) =>
      api.companies({ name: search, page: pageParam, page_size: 100 }),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    enabled: permitted,
  });
  const selected = useQuery({
    queryKey: ['property-companies', 'detail', value],
    queryFn: () => api.company(value!),
    enabled: permitted && !!value,
  });
  if (!permitted)
    return (
      <Input
        value={value}
        onChange={(event) => onChange?.(event.target.value || undefined)}
        placeholder="请输入物业公司 ID"
      />
    );
  const choices = new Map(
    query.data?.pages
      .flatMap((page) => page.items)
      .map((item) => [item.id, item]) ?? [],
  );
  if (selected.data) choices.set(selected.data.id, selected.data);
  return (
    <>
      {(query.isError || selected.isError) && (
        <ReadError
          retry={() => {
            void query.refetch();
            if (value) void selected.refetch();
          }}
        />
      )}
      <Select
        value={value}
        onChange={onChange}
        allowClear
        showSearch={{ filterOption: false, onSearch: setSearch }}
        loading={query.isFetching}
        placeholder="选择物业公司"
        options={[...choices.values()].map((item) => ({
          value: item.id,
          label: `${item.name}（${item.code}）${item.enabled ? '' : ' · 停用'}`,
        }))}
        popupRender={(menu) => (
          <>
            {menu}
            {query.hasNextPage && (
              <Space style={{ padding: 8 }}>
                <Button
                  loading={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}
                >
                  加载更多公司
                </Button>
              </Space>
            )}
          </>
        )}
      />
    </>
  );
}
