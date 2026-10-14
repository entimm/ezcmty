import type { AdminScope } from './admin-types';

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  code: string;
  request_id: string;
  errors?: unknown;
}

export type AdminRequestOptions = Omit<
  RequestInit,
  'credentials' | 'redirect'
> & {
  ignoreUnauthorized?: boolean;
};

export type AdminRequest = <T>(
  path: string,
  options?: AdminRequestOptions,
) => Promise<T>;

export class ApiError extends Error {
  constructor(
    readonly scope: AdminScope,
    readonly status: number,
    readonly problem?: ProblemDetails,
    readonly requestId?: string,
    readonly retryAfter?: string,
  ) {
    super(problem?.detail || problem?.title || `请求失败（${status}）`);
    this.name = 'ApiError';
  }
}

function parseProblem(
  body: unknown,
  status: number,
): ProblemDetails | undefined {
  if (!body || typeof body !== 'object') return;
  const value = body as Record<string, unknown>;
  const fields = ['type', 'title', 'detail', 'instance', 'code', 'request_id'];
  if (
    value.status === status &&
    fields.every((field) => typeof value[field] === 'string')
  ) {
    return value as unknown as ProblemDetails;
  }
}

export function createAdminRequestClient({
  scope,
  basePath,
  onUnauthorized,
  getCsrfToken,
  onPasswordChangeRequired,
}: {
  scope: AdminScope;
  basePath: string;
  onUnauthorized: () => void;
  getCsrfToken?: () => string | undefined;
  onPasswordChangeRequired?: () => void;
}) {
  if (!basePath.startsWith('/') || basePath.startsWith('//')) {
    throw new Error('管理后台 API 前缀必须为同源绝对路径');
  }
  const base = new URL(basePath, window.location.origin);
  const prefix = base.pathname.replace(/\/+$/, '');
  if (
    base.origin !== window.location.origin ||
    !prefix ||
    base.search ||
    base.hash
  ) {
    throw new Error('管理后台 API 前缀必须限定后台路径');
  }

  let generation = 0;
  const pending = new Set<AbortController>();

  function cancel() {
    generation += 1;
    for (const controller of pending) controller.abort();
    pending.clear();
  }

  const request: AdminRequest = async <T>(
    path: string,
    options: AdminRequestOptions = {},
  ): Promise<T> => {
    if (!path.startsWith('/') || path.startsWith('//')) {
      throw new Error('请求路径必须相对于当前后台 API 前缀');
    }
    const url = new URL(`${prefix}${path}`, base.origin);
    if (
      url.origin !== base.origin ||
      !url.pathname.startsWith(`${prefix}/`) ||
      url.hash
    ) {
      throw new Error('请求路径不能越过当前后台 API 前缀');
    }

    const currentGeneration = generation;
    const controller = new AbortController();
    const abort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener('abort', abort, { once: true });
    pending.add(controller);

    const assertCurrent = () => {
      if (currentGeneration !== generation || controller.signal.aborted) {
        throw new DOMException('请求所属会话已失效', 'AbortError');
      }
    };

    try {
      assertCurrent();
      const { ignoreUnauthorized, ...fetchOptions } = options;
      const headers = new Headers(fetchOptions.headers);
      if (!headers.has('Accept')) headers.set('Accept', 'application/json');
      const csrf = getCsrfToken?.();
      if (
        csrf &&
        !['GET', 'HEAD', 'OPTIONS'].includes(
          (fetchOptions.method || 'GET').toUpperCase(),
        )
      ) {
        headers.set('X-CSRF-Token', csrf);
      }
      const response = await fetch(url.toString(), {
        ...fetchOptions,
        headers,
        credentials: 'same-origin',
        redirect: 'error',
        signal: controller.signal,
      });
      assertCurrent();

      const text = await response.text();
      assertCurrent();
      let body: unknown;
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          if (response.ok) throw new Error('服务器未返回有效的 JSON 响应');
        }
      }

      if (!response.ok) {
        const problem = response.headers
          .get('Content-Type')
          ?.includes('application/problem+json')
          ? parseProblem(body, response.status)
          : undefined;
        const error = new ApiError(
          scope,
          response.status,
          problem,
          problem?.request_id ||
            response.headers.get('X-Request-ID') ||
            undefined,
          response.headers.get('Retry-After') || undefined,
        );
        if (response.status === 401 && !ignoreUnauthorized) onUnauthorized();
        if (problem?.code === 'auth.password_change_required')
          onPasswordChangeRequired?.();
        throw error;
      }

      return body as T;
    } finally {
      options.signal?.removeEventListener('abort', abort);
      pending.delete(controller);
    }
  };

  return { scope, request, cancel };
}
