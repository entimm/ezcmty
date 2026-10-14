import { useSearchParams } from '@umijs/max';

export function useListState(prefix = '') {
  const [urlParams, setParams] = useSearchParams();
  const params = prefix
    ? new URLSearchParams(
        [...urlParams]
          .filter(([key]) => key.startsWith(prefix))
          .map(([key, value]) => [key.slice(prefix.length), value]),
      )
    : urlParams;
  const number = (key: string, fallback: number, max: number) => {
    const value = Number(params.get(key));
    return Number.isInteger(value) && value >= 1 && value <= max
      ? value
      : fallback;
  };
  const page = number('page', 1, 1000000),
    pageSize = number('page_size', 20, 100);
  const update = (values: Record<string, string | number | undefined>) =>
    (() => {
      const next = new URLSearchParams(urlParams);
      for (const [key, value] of Object.entries(values))
        if (value === undefined || value === '') next.delete(`${prefix}${key}`);
        else next.set(`${prefix}${key}`, String(value));
      setParams(next);
    })();
  return {
    params,
    page,
    pageSize,
    update,
    pagination: {
      current: page,
      pageSize,
      showSizeChanger: true,
      onChange: (nextPage: number, nextSize: number) =>
        update({
          page: nextSize !== pageSize ? 1 : nextPage,
          page_size: nextSize,
        }),
    },
  };
}
