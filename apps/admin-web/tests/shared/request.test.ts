import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  createRequestClient,
  type Download,
} from '../../src/shared/request';

afterEach(() => vi.unstubAllGlobals());
function json(body: unknown, status = 200, headers: HeadersInit = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}
function problem(code: string, status: number) {
  return json(
    {
      type: 'https://errors.example/' + code,
      title: '业务处理失败',
      detail: '请按当前状态处理',
      status,
      code,
      request_id: 'request-1',
    },
    status,
    { 'Content-Type': 'application/problem+json' },
  );
}
function harness(
  scope: 'platform_admin' | 'property_admin' = 'platform_admin',
) {
  const onUnauthorized = vi.fn(),
    onPasswordChangeRequired = vi.fn();
  const client = createRequestClient({
    scope,
    basePath: scope === 'platform_admin' ? '/api/platform' : '/api/property',
    getCsrfToken: () => 'csrf-current',
    onUnauthorized,
    onPasswordChangeRequired,
  });
  return { ...client, onUnauthorized, onPasswordChangeRequired };
}

describe('后台请求隔离与安全状态', () => {
  it.each([
    ['GET', '网络连接失败，请检查网络后重试。'],
    ['POST', '网络连接中断，写入结果尚未确定，请先核实原记录。'],
  ])(
    '网络中断时区分%s读取与未知写入结果，且不自动重发',
    async (method, message) => {
      const fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
      vi.stubGlobal('fetch', fetch);
      await expect(
        harness().request('/v1/resource', { method }),
      ).rejects.toThrow(message);
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );
  it('请求限定本端 API，附带同源会话且拒绝重定向', async () => {
    const fetch = vi.fn().mockResolvedValue(json({ items: [] }));
    vi.stubGlobal('fetch', fetch);
    const client = harness();
    expect(await client.request('/v1/admin-accounts')).toEqual({ items: [] });
    const [url, options] = fetch.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe(
      '/api/platform/v1/admin-accounts',
    );
    expect(options).toMatchObject({
      credentials: 'same-origin',
      redirect: 'error',
    });
    expect(options.headers.get('Accept')).toBe('application/json');
    expect(options.headers.has('X-CSRF-Token')).toBe(false);
  });
  it('所有写请求取当前 CSRF，204 正常返回且写入失败不会自动重试', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(problem('property.conflict', 409));
    vi.stubGlobal('fetch', fetch);
    const client = harness();
    expect(
      await client.request('/v1/example', { method: 'POST', body: '{}' }),
    ).toBeUndefined();
    expect(fetch.mock.calls[0][1].headers.get('X-CSRF-Token')).toBe(
      'csrf-current',
    );
    await expect(
      client.request('/v1/example', { method: 'PATCH', body: '{}' }),
    ).rejects.toMatchObject({ status: 409 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('认证失效只通知所属客户端，登录探测可抑制失效通知', async () => {
    const fetch = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(problem('auth.unauthenticated', 401)),
      );
    vi.stubGlobal('fetch', fetch);
    const platform = harness(),
      property = harness('property_admin');
    await expect(platform.request('/v1/profile')).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(platform.onUnauthorized).toHaveBeenCalledOnce();
    expect(property.onUnauthorized).not.toHaveBeenCalled();
    await expect(
      platform.request('/v1/auth/session', { ignoreUnauthorized: true }),
    ).rejects.toMatchObject({ status: 401 });
    expect(platform.onUnauthorized).toHaveBeenCalledOnce();
  });
  it('只有明确的改密错误进入受限状态，普通 403 保留会话', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(problem('auth.forbidden', 403))
      .mockResolvedValueOnce(problem('auth.password_change_required', 403));
    vi.stubGlobal('fetch', fetch);
    const client = harness();
    await expect(client.request('/v1/admin-accounts')).rejects.toMatchObject({
      status: 403,
    });
    expect(client.onPasswordChangeRequired).not.toHaveBeenCalled();
    await expect(client.request('/v1/admin-accounts')).rejects.toMatchObject({
      status: 403,
      requestId: 'request-1',
    });
    expect(client.onPasswordChangeRequired).toHaveBeenCalledOnce();
    expect(client.onUnauthorized).not.toHaveBeenCalled();
  });
  it.each([
    '//evil.example/v1/profile',
    'https://evil.example',
    '/../property/v1/profile',
    '/v1/../../property/v1/profile',
    '/v1/profile#fragment',
  ])('拒绝越界路径且不发送网络请求：%s', async (path) => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    await expect(harness().request(path)).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('取消旧身份请求后，即使网络晚到成功也不能回填旧数据', async () => {
    let deliver!: (response: Response) => void;
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          deliver = resolve;
        }),
    );
    vi.stubGlobal('fetch', fetch);
    const client = harness(),
      pending = client.request('/v1/profile');
    client.cancel();
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    deliver(json({ display_name: '旧身份数据' }));
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(client.onUnauthorized).not.toHaveBeenCalled();
  });
  it('调用方预先取消时传递中止信号，且不返回响应数据', async () => {
    const fetch = vi.fn().mockResolvedValue(json({ ok: true }));
    vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    controller.abort();
    await expect(
      harness().request('/v1/profile', { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    if (fetch.mock.calls.length)
      expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
  });
  it('下载保留二进制和 UTF-8 文件名，并去除文件路径字符', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response('示例文件', {
        status: 200,
        headers: {
          'Content-Disposition':
            "attachment; filename*=UTF-8''%E8%B4%A6%E5%8D%95%2F2026.csv",
        },
      }),
    );
    vi.stubGlobal('fetch', fetch);
    const result = await harness().request<Download>('/v1/imports/template', {
      responseType: 'download',
    });
    expect(result.fileName).toBe('账单_2026.csv');
    expect(await result.blob.text()).toBe('示例文件');
    expect(fetch.mock.calls[0][1].headers.get('Accept')).toBe('*/*');
  });
  it('成功响应格式错误时明确失败，不把 HTML 当成业务资源', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response('<html>错误</html>', { status: 200 })),
    );
    await expect(harness().request('/v1/profile')).rejects.toThrow(
      '服务端返回格式错误',
    );
  });
});
