import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Select, Spin, Button } from 'antd';
import { useAdmin } from '../../shared/context';
import { createPlatformApi, type Company } from './api';
export {
  time,
  errorText,
  Person,
  ReadState,
  emptyList,
  ListFilter,
  PasswordFields,
  pagination,
  SystemFormDialog as PlatformFormDialog,
  useSystemWrite as usePlatformWrite,
} from '../../shared/system/components';
export function usePlatformApi() {
  const { request, scope } = useAdmin();
  if (scope !== 'platform') throw new Error('平台业务只能在平台后台运行');
  return useMemo(() => createPlatformApi(request), [request]);
}

export function CompanyPicker({
  value,
  onChange,
  selected,
}: {
  value?: string;
  onChange?: (value: string | undefined) => void;
  selected?: Company;
}) {
  const api = usePlatformApi();
  const [search, setSearch] = useState('');
  const query = useQuery({
    queryKey: ['platform', 'company-options', search],
    queryFn: () =>
      api.companyOptions({
        name: search || undefined,
        page: 1,
        page_size: 100,
      }),
    enabled: true,
  });
  const options = new Map(
    (query.data?.items ?? []).map((company) => [company.id, company]),
  );
  if (selected) options.set(selected.id, selected);
  return (
    <>
      <Select
        allowClear
        showSearch
        filterOption={false}
        placeholder="选择物业公司"
        aria-label="所属物业公司"
        value={value}
        onChange={onChange}
        onSearch={setSearch}
        loading={query.isFetching}
        options={[...options.values()].map((company) => ({
          value: company.id,
          label: company.name + (company.enabled ? '' : '（公司停用）'),
        }))}
        style={{ minWidth: 230 }}
        notFoundContent={
          query.isError ? (
            '公司加载失败，请重试'
          ) : query.isFetching ? (
            <Spin size="small" />
          ) : (
            '未找到公司'
          )
        }
      />
      <span className="sr-only">
        {query.data && query.data.total > 100
          ? '请搜索公司名称以缩小选择范围'
          : ''}
      </span>
      {query.isError && (
        <Button size="small" onClick={() => void query.refetch()}>
          重试
        </Button>
      )}
    </>
  );
}
