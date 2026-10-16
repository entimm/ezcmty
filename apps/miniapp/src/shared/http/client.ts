export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId = '',
  ) {
    super(message);
  }
}

export class StaleSessionError extends Error {}
export type HttpMethod = 'GET' | 'POST' | 'DELETE';

export function request<T>(
  base: string,
  path: string,
  options: {
    method?: HttpMethod;
    data?: object;
    token?: string;
    key?: string;
    register?: (task: WechatMiniprogram.RequestTask) => () => void;
  } = {},
): Promise<T> {
  return new Promise((resolve, reject) => {
    let unregister = () => {};
    const task = wx.request({
      url: base + '/v1' + path,
      method: options.method || 'GET',
      data: options.data,
      timeout: 12000,
      header: {
        'Content-Type': 'application/json',
        ...(options.token ? { Authorization: 'Bearer ' + options.token } : {}),
        ...(options.key ? { 'Idempotency-Key': options.key } : {}),
      },
      success(response) {
        const body = response.data as {
          code?: string;
          detail?: string;
          request_id?: string;
        };
        if (response.statusCode >= 200 && response.statusCode < 300)
          resolve(response.data as T);
        else
          reject(
            new ApiError(
              response.statusCode,
              body?.code || 'HTTP_ERROR',
              body?.detail || '暂时无法完成，请稍后重试',
              body?.request_id,
            ),
          );
      },
      fail() {
        reject(new ApiError(0, 'network', '网络连接失败，请检查网络后重试'));
      },
      complete() {
        unregister();
      },
    });
    unregister = options.register?.(task) || unregister;
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

export function errorText(error: unknown): string {
  if (error instanceof StaleSessionError) return '';
  if (error instanceof ApiError) return error.message;
  return '暂时无法完成，请稍后重试';
}
