import type { AdminDownload, AdminRequest } from '../request-client';
import { queryString } from '../api/query-string';
import type {
  Batch,
  BatchAction,
  BatchCreate,
  ConfirmInput,
  ErrorFile,
  Filters,
  ImportEvent,
  ImportRow,
  ImportType,
  Issue,
  Page,
  Template,
} from './types';
export function createImportsApi(transport: AdminRequest) {
  const request: AdminRequest = (path, options) =>
    transport(path, { cache: 'no-store', ...options });
  const path = (id: string) => `/v1/import-batches/${encodeURIComponent(id)}`;
  const templatePath = (key: string, version: number) =>
    `/v1/import-types/${encodeURIComponent(key)}/versions/${version}`;
  const post = <T>(
    url: string,
    body: unknown,
    key: string,
    signal?: AbortSignal,
  ) =>
    request<T>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  return {
    types: (signal?: AbortSignal) =>
      request<{ items: ImportType[] }>('/v1/import-types', { signal }),
    template: (key: string, version: number, signal?: AbortSignal) =>
      request<Template>(templatePath(key, version), { signal }),
    templateDownload: (key: string, version: number, signal?: AbortSignal) =>
      request<AdminDownload>(`${templatePath(key, version)}/template-file`, {
        responseType: 'download',
        signal,
      }),
    batches: (filters: Filters, signal?: AbortSignal) =>
      request<Page<Batch>>(`/v1/import-batches?${queryString(filters)}`, {
        signal,
      }),
    batch: (id: string, signal?: AbortSignal) =>
      request<Batch>(path(id), { signal }),
    rows: (id: string, filters: Filters, signal?: AbortSignal) =>
      request<Page<ImportRow>>(`${path(id)}/rows?${queryString(filters)}`, {
        signal,
      }),
    issues: (id: string, filters: Filters, signal?: AbortSignal) =>
      request<Page<Issue>>(`${path(id)}/issues?${queryString(filters)}`, {
        signal,
      }),
    events: (id: string, filters: Filters, signal?: AbortSignal) =>
      request<Page<ImportEvent>>(`${path(id)}/events?${queryString(filters)}`, {
        signal,
      }),
    create: (body: BatchCreate, key: string) =>
      post<BatchAction>('/v1/import-batches', body, key),
    upload: (
      id: string,
      file: File,
      key: string,
      signal: AbortSignal,
      onUploadProgress: (loaded: number, total: number | null) => void,
    ) => {
      const body = new FormData();
      body.append('file', file);
      return request<BatchAction>(`${path(id)}/source-file`, {
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': key },
        signal,
        onUploadProgress,
      });
    },
    precheck: (id: string, body: { preview_version: number }, key: string) =>
      post<BatchAction>(`${path(id)}/precheck`, body, key),
    confirm: (id: string, body: ConfirmInput, key: string) =>
      post<BatchAction>(`${path(id)}/confirm`, body, key),
    cancel: (id: string, key: string) =>
      post<BatchAction>(`${path(id)}/cancel`, undefined, key),
    retry: (id: string, key: string) =>
      post<{
        source_batch_id: string;
        selected_rows: number;
        batch: BatchAction;
      }>(`${path(id)}/retry-failed`, { selection: 'retryable_only' }, key),
    recover: (id: string, body: { reason: string }, key: string) =>
      post<BatchAction>(`${path(id)}/recover`, body, key),
    generateErrorFile: (
      id: string,
      body: { format: 'csv' | 'xlsx'; preview_version: number },
      key: string,
    ) =>
      post<{
        batch_id: string;
        status: ErrorFile['status'];
        generation: number;
        source_preview_version: number;
        task: NonNullable<BatchAction['active_task']>;
      }>(`${path(id)}/error-file`, body, key),
    errorFile: (id: string, signal?: AbortSignal) =>
      request<ErrorFile>(`${path(id)}/artifacts/error-file`, { signal }),
    download: (id: string, generation: number) =>
      request<AdminDownload>(
        `${path(id)}/artifacts/error-file/download?generation=${generation}`,
        { responseType: 'download' },
      ),
  };
}
export type ImportsApi = ReturnType<typeof createImportsApi>;
export function saveDownload(value: AdminDownload) {
  const url = URL.createObjectURL(value.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = value.fileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
