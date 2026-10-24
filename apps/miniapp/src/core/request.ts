export type HttpMethod = 'GET' | 'POST' | 'DELETE';

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId = '',
    public retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class StaleSessionError extends Error {
  constructor() {
    super('会话或页面已变化');
    this.name = 'StaleSessionError';
  }
}

export interface RequestOptions {
  method?: HttpMethod;
  data?: object;
  token?: string;
  key?: string;
  register?: (task: WechatMiniprogram.RequestTask) => () => void;
}

export function request<T>(
  base: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  return new Promise((resolve, reject) => {
    let unregister = () => {};
    let completed = false;
    let task: WechatMiniprogram.RequestTask;
    try {
      task = wx.request({
        url: base.replace(/\/$/, '') + '/v1' + path,
        method: options.method || 'GET',
        data: options.data,
        timeout: 15000,
        header: {
          'Content-Type': 'application/json',
          ...(options.token
            ? { Authorization: 'Bearer ' + options.token }
            : {}),
          ...(options.key ? { 'Idempotency-Key': options.key } : {}),
        },
        success(response) {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            resolve(response.data as T);
            return;
          }
          const body = response.data as {
            code?: string;
            detail?: string;
            request_id?: string;
          } | null;
          const headers = (response.header || {}) as Record<string, unknown>;
          const retry = Number(
            headers['Retry-After'] ?? headers['retry-after'],
          );
          reject(
            new ApiError(
              response.statusCode,
              typeof body?.code === 'string' ? body.code : 'http.error',
              typeof body?.detail === 'string'
                ? body.detail
                : '暂时无法完成，请稍后重试',
              typeof body?.request_id === 'string' ? body.request_id : '',
              Number.isFinite(retry) && retry > 0
                ? Math.ceil(retry)
                : undefined,
            ),
          );
        },
        fail() {
          // Native errors may contain credentials or URLs; never expose or log them.
          reject(
            new ApiError(
              0,
              'network.unavailable',
              '网络连接失败，请检查网络后重试',
            ),
          );
        },
        complete() {
          completed = true;
          unregister();
        },
      });
    } catch {
      reject(
        new ApiError(
          0,
          'network.unavailable',
          '网络连接失败，请检查网络后重试',
        ),
      );
      return;
    }
    unregister = options.register?.(task) || unregister;
    if (completed) unregister();
  });
}

export function query(
  values: Record<string, string | number | undefined>,
): string {
  const parts = Object.keys(values)
    .filter((key) => values[key] !== undefined && values[key] !== '')
    .map(
      (key) =>
        encodeURIComponent(key) + '=' + encodeURIComponent(String(values[key])),
    );
  return parts.length ? '?' + parts.join('&') : '';
}

export const isUnknownResult = (error: unknown): boolean =>
  error instanceof ApiError && (error.status === 0 || error.status >= 500);

export function errorText(error: unknown, fallback?: string): string {
  if (error instanceof StaleSessionError) return '';
  if (fallback) return fallback;
  if (error instanceof ApiError) {
    if (error.status === 401) return '登录已过期，请重新微信登录';
    if (error.status === 403) return '当前账号暂时无法使用此功能';
    if (error.status === 404) return '内容不存在或当前无权访问，请返回刷新';
    if (error.status === 429)
      return error.retryAfterSeconds
        ? `操作较频繁，请 ${error.retryAfterSeconds} 秒后重试`
        : '操作较频繁，请稍后重试';
    return error.message;
  }
  return error instanceof Error && error.message
    ? error.message
    : '暂时无法完成，请稍后重试';
}
