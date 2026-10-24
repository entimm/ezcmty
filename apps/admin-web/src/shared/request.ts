import type { AdminScope, ProblemDetails } from './types';
export interface Download {
  blob: Blob;
  fileName: string;
}
export interface RequestOptions extends RequestInit {
  ignoreUnauthorized?: boolean;
  responseType?: 'download';
  onUploadProgress?: (loaded: number, total: number | null) => void;
}
export type AdminRequest = <T>(
  path: string,
  options?: RequestOptions,
) => Promise<T>;
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem?: ProblemDetails,
    readonly requestId?: string,
    readonly retryAfter?: string,
  ) {
    super(problem?.detail || problem?.title || `请求失败（${status}）`);
    this.name = 'ApiError';
  }
}
export function queryString(values: object) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '')
      query.set(key, String(value));
  });
  return query.toString();
}
export function createRequestClient({
  scope,
  basePath,
  getCsrfToken,
  onUnauthorized,
  onPasswordChangeRequired,
}: {
  scope: AdminScope;
  basePath: string;
  getCsrfToken: () => string | undefined;
  onUnauthorized: () => void;
  onPasswordChangeRequired?: () => void;
}) {
  if (!basePath.startsWith('/') || basePath.startsWith('//'))
    throw new Error('API 必须为本后台同源路径');
  const base = new URL(basePath, window.location.origin),
    prefix = base.pathname.replace(/\/+$/, '');
  if (
    base.origin !== window.location.origin ||
    !prefix ||
    base.search ||
    base.hash
  )
    throw new Error('API 前缀不合法');
  let generation = 0;
  const pending = new Set<AbortController>();
  const cancel = () => {
    generation++;
    pending.forEach((c) => c.abort());
    pending.clear();
  };
  const request: AdminRequest = async <T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<T> => {
    if (!path.startsWith('/') || path.startsWith('//'))
      throw new Error('请求必须限定当前后台');
    const url = new URL(prefix + path, base.origin);
    if (
      url.origin !== base.origin ||
      !url.pathname.startsWith(prefix + '/') ||
      url.hash
    )
      throw new Error('请求不能越过当前后台');
    const { ignoreUnauthorized, responseType, onUploadProgress, ...init } =
      options;
    const controller = new AbortController(),
      version = generation;
    pending.add(controller);
    const abort = () => controller.abort();
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener('abort', abort, { once: true });
    const current = () => {
      if (version !== generation || controller.signal.aborted)
        throw new DOMException('当前会话请求已取消', 'AbortError');
    };
    try {
      const headers = new Headers(init.headers);
      headers.set(
        'Accept',
        responseType === 'download' ? '*/*' : 'application/json',
      );
      const method = (init.method || 'GET').toUpperCase(),
        csrf = getCsrfToken();
      if (csrf && !['GET', 'HEAD', 'OPTIONS'].includes(method))
        headers.set('X-CSRF-Token', csrf);
      let response: Response;
      if (
        onUploadProgress &&
        typeof XMLHttpRequest !== 'undefined' &&
        init.body instanceof FormData
      ) {
        response = await new Promise<Response>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open(method, url.toString());
          xhr.withCredentials = true;
          headers.forEach((v, k) => xhr.setRequestHeader(k, v));
          xhr.responseType = 'blob';
          xhr.upload.onprogress = (e) =>
            onUploadProgress(e.loaded, e.lengthComputable ? e.total : null);
          xhr.onload = () => {
            const responseHeaders = new Headers();
            xhr
              .getAllResponseHeaders()
              .trim()
              .split(/[\r\n]+/)
              .forEach((line) => {
                const i = line.indexOf(':');
                if (i > 0)
                  responseHeaders.append(
                    line.slice(0, i),
                    line.slice(i + 1).trim(),
                  );
              });
            resolve(
              new Response(xhr.response, {
                status: xhr.status,
                headers: responseHeaders,
              }),
            );
          };
          xhr.onerror = () =>
            reject(new TypeError('网络连接中断，请核实原请求结果'));
          xhr.onabort = () =>
            reject(
              new DOMException('上传已中断，请核实批次状态', 'AbortError'),
            );
          const stop = () => xhr.abort();
          controller.signal.addEventListener('abort', stop, { once: true });
          xhr.onloadend = () =>
            controller.signal.removeEventListener('abort', stop);
          current();
          xhr.send(init.body as FormData);
        });
      } else
        response = await fetch(url, {
          ...init,
          headers,
          credentials: 'same-origin',
          redirect: 'error',
          signal: controller.signal,
        });
      current();
      if (response.ok && responseType === 'download') {
        const blob = await response.blob();
        current();
        const raw = response.headers.get('Content-Disposition') || '';
        const encoded = raw.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
        let fileName = 'download';
        try {
          fileName = encoded
            ? decodeURIComponent(encoded)
            : raw.match(/filename="?([^";]+)"?/i)?.[1] || fileName;
        } catch {
          /* Use a safe fallback name. */
        }
        return {
          blob,
          fileName: Array.from(fileName)
            .map((c) =>
              c.charCodeAt(0) < 32 || c === '/' || c === '\\' ? '_' : c,
            )
            .join('')
            .slice(0, 255),
        } as T;
      }
      const text = await response.text();
      current();
      let value: unknown;
      try {
        value = text ? JSON.parse(text) : undefined;
      } catch {
        if (response.ok) throw new Error('服务端返回格式错误');
      }
      if (!response.ok) {
        const problem =
          response.headers
            .get('Content-Type')
            ?.includes('application/problem+json') &&
          value &&
          typeof value === 'object'
            ? (value as ProblemDetails)
            : undefined;
        const error = new ApiError(
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
      return value as T;
    } catch (failure) {
      if (failure instanceof TypeError) {
        const reading = ['GET', 'HEAD', 'OPTIONS'].includes(
          (options.method || 'GET').toUpperCase(),
        );
        throw new Error(
          reading
            ? '网络连接失败，请检查网络后重试。'
            : '网络连接中断，写入结果尚未确定，请先核实原记录。',
          { cause: failure },
        );
      }
      throw failure;
    } finally {
      pending.delete(controller);
      options.signal?.removeEventListener('abort', abort);
    }
  };
  return { scope, request, cancel };
}
