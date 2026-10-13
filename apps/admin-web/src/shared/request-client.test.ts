import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, createAdminRequestClient } from './request-client';

afterEach(() => vi.unstubAllGlobals());

function client(scope: 'platform_admin' | 'property_admin' = 'platform_admin') {
  const onUnauthorized = vi.fn();
  return {
    ...createAdminRequestClient({
      scope,
      basePath: scope === 'platform_admin' ? '/api/platform' : '/api/property',
      onUnauthorized,
    }),
    onUnauthorized,
  };
}

function problem(status: number) {
  return {
    type: 'https://example.test/problems/http.error',
    title: '请求被拒绝',
    status,
    detail: '当前操作不可用',
    instance: 'urn:request:test-request',
    code: 'http.error',
    request_id: 'test-request',
  };
}

describe('scoped API requests', () => {
  it('reads resources directly and sends each request to its own Cookie API', async () => {
    const resource = { items: [{ id: '1' }], total: 1, page: 1, page_size: 20 };
    const fetcher = vi.fn<typeof fetch>(async () => Response.json(resource));
    vi.stubGlobal('fetch', fetcher);

    expect(await client().request('/v1/resources?page=1')).toEqual(resource);
    await client('property_admin').request('/v1/resources');

    expect(fetcher.mock.calls[0][0]).toBe(
      `${window.location.origin}/api/platform/v1/resources?page=1`,
    );
    expect(fetcher.mock.calls[1][0]).toBe(
      `${window.location.origin}/api/property/v1/resources`,
    );
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      credentials: 'same-origin',
      redirect: 'error',
    });
  });

  it('accepts a 204 response without a JSON body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 204 })),
    );
    await expect(
      client().request('/v1/resources/1', { method: 'DELETE' }),
    ).resolves.toBeUndefined();
  });

  it('preserves Problem Details and request IDs without invalidating a 403 session', async () => {
    const details = problem(403);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(details, {
          status: 403,
          headers: { 'Content-Type': 'application/problem+json' },
        }),
      ),
    );
    const api = client();
    await expect(api.request('/v1/resources')).rejects.toMatchObject({
      name: 'ApiError',
      scope: 'platform_admin',
      status: 403,
      problem: details,
      requestId: 'test-request',
    });
    expect(api.onUnauthorized).not.toHaveBeenCalled();
  });

  it('invalidates only the scope receiving a 401, including non-JSON errors', async () => {
    const fetcher = vi.fn(async (url: string) =>
      url.includes('/platform/')
        ? new Response('Unauthorized', { status: 401 })
        : Response.json({ id: 'property' }),
    );
    vi.stubGlobal('fetch', fetcher);
    const platform = client();
    const property = client('property_admin');
    await expect(platform.request('/v1/resources')).rejects.toBeInstanceOf(
      ApiError,
    );
    await expect(property.request('/v1/resources')).resolves.toEqual({
      id: 'property',
    });
    expect(platform.onUnauthorized).toHaveBeenCalledOnce();
    expect(property.onUnauthorized).not.toHaveBeenCalled();
  });

  it.each([
    'https://other.test/v1/data',
    '//other.test/data',
    '/../property/v1/data',
    '/%2e%2e/property/v1/data',
  ])('rejects paths outside the scope: %s', async (path) => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    await expect(client().request(path)).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([200, 401])(
    'rejects an old %s response even when the transport ignores cancellation',
    async (status) => {
      let finish!: (response: Response) => void;
      const fetcher = vi.fn<typeof fetch>(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      );
      vi.stubGlobal('fetch', fetcher);
      const api = client();
      const pending = api.request('/v1/resources');
      const result = expect(pending).rejects.toMatchObject({
        name: 'AbortError',
      });
      api.cancel();
      expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
      finish(Response.json({ id: 'old-user' }, { status }));
      await result;
      expect(api.onUnauthorized).not.toHaveBeenCalled();
    },
  );

  it('honors caller cancellation before starting a request', async () => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    const controller = new AbortController();
    controller.abort();
    await expect(
      client().request('/v1/resources', { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('does not retry writes on conflicts', async () => {
    const fetcher = vi.fn(async () =>
      Response.json(problem(409), {
        status: 409,
        headers: { 'Content-Type': 'application/problem+json' },
      }),
    );
    vi.stubGlobal('fetch', fetcher);
    await expect(
      client().request('/v1/resources', { method: 'POST' }),
    ).rejects.toMatchObject({ status: 409 });
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
