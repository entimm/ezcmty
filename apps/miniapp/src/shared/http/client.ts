interface NetworkDiagnostics {
  method: HttpMethod;
  url: string;
  errMsg: string;
  errno?: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId = '',
    public diagnostics?: NetworkDiagnostics,
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
      fail(error) {
        const diagnostics: NetworkDiagnostics = {
          method: options.method || 'GET',
          url: (base + '/v1' + path).split(/[?#]/, 1)[0],
          errMsg:
            error?.errMsg?.replace(
              /https?:\/\/[^\s"'<>]+/gi,
              (url) => url.split(/[?#]/, 1)[0],
            ) || 'request:fail',
          errno: error?.errno,
        };
        try {
          console.error('[http] wx.request failed', diagnostics);
          wx.getRealtimeLogManager?.().error(
            '[http] wx.request failed',
            diagnostics,
          );
        } catch {
          // Diagnostics must remain available even when log reporting fails.
        }
        reject(
          new ApiError(
            0,
            'network',
            '网络连接失败，请检查网络后重试',
            '',
            diagnostics,
          ),
        );
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

export function errorText(error: unknown, message?: string): string {
  if (error instanceof StaleSessionError) return '';
  if (error instanceof ApiError) {
    const summary = message ?? error.message;
    const details = error.diagnostics;
    if (!details) return summary;
    return [
      summary,
      'errMsg: ' + details.errMsg,
      ...(typeof details.errno === 'number' ? ['errno: ' + details.errno] : []),
      details.method + ' ' + details.url,
    ].join('\n');
  }
  return message ?? '暂时无法完成，请稍后重试';
}
