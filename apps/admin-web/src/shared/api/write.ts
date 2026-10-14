import type { AdminRequest } from '../request-client';

export function createJsonWriter(request: AdminRequest) {
  return <T>(path: string, method: string, data?: unknown) =>
    request<T>(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
}
