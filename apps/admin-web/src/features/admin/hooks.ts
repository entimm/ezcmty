import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { App } from 'antd';
import { history, useSearchParams } from '@umijs/max';
import { useAdminSession } from '../../auth/use-admin-session';
import { createAdminApi } from '../../shared/admin-api';
import { ApiError } from '../../shared/request-client';

export function useAdminApi() {
  const { request } = useAdminSession();
  return useMemo(() => createAdminApi(request), [request]);
}
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
export function useAdminOperation(resources = ['accounts', 'roles', 'audit']) {
  const { refreshSession } = useAdminSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      run,
      security,
    }: {
      run: () => Promise<unknown>;
      security?: boolean;
    }) => {
      const value = await run();
      if (security) await refreshSession();
      await Promise.all(
        resources.map((key) => client.invalidateQueries({ queryKey: [key] })),
      );
      return value;
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void Promise.all(
          resources
            .filter((key) => key !== 'audit')
            .map((key) => client.invalidateQueries({ queryKey: [key] })),
        );
    },
    retry: false,
    gcTime: 0,
  });
}
export function useDirtyForm() {
  const [dirty, setDirty] = useState(false);
  const { modal } = App.useApp();
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', unload);
    const unblock = history?.block((transition) => {
      modal.confirm({
        title: '放弃未保存的修改？',
        onOk: () => {
          unblock();
          transition.retry();
        },
      });
    });
    return () => {
      unblock?.();
      window.removeEventListener('beforeunload', unload);
    };
  }, [dirty, modal]);
  return {
    changed: () => setDirty(true),
    reset: () => setDirty(false),
    close: (done: () => void) => {
      if (dirty) modal.confirm({ title: '放弃未保存的修改？', onOk: done });
      else done();
    },
  };
}
