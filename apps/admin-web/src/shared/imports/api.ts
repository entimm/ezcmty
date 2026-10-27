import type { components } from '../../../../../openapi/types';
import type { AdminRequest, Download } from '../request';
import type {
  Batch,
  BatchAction,
  BatchCreate,
  ConfirmInput,
  ErrorFile,
  Filters,
  ImportEvent,
  ImportRow,
  Issue,
  Page,
  Template,
} from './types';
type Schemas = components['schemas'];
export function query(filters: Filters) {
  const q = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== '') q.set(key, String(value));
  });
  return q.toString();
}
export function createImportsApi(request: AdminRequest) {
  const root = (id: string) => `/v1/import-batches/${encodeURIComponent(id)}`;
  const post = <T>(url: string, body: unknown, key: string) =>
    request<T>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  return {
    types: () => request<Schemas['ImportTypeList']>('/v1/import-types'),
    template: (key: string, version: number) =>
      request<Template>(
        `/v1/import-types/${encodeURIComponent(key)}/versions/${version}`,
      ),
    templateDownload: (key: string, version: number) =>
      request<Download>(
        `/v1/import-types/${encodeURIComponent(key)}/versions/${version}/template-file`,
        { responseType: 'download' },
      ),
    batches: (filters: Filters) =>
      request<Page<Batch>>(`/v1/import-batches?${query(filters)}`),
    batch: (id: string) => request<Batch>(root(id)),
    rows: (id: string, filters: Filters) =>
      request<Page<ImportRow>>(`${root(id)}/rows?${query(filters)}`),
    issues: (id: string, filters: Filters) =>
      request<Page<Issue>>(`${root(id)}/issues?${query(filters)}`),
    events: (id: string, filters: Filters) =>
      request<Page<ImportEvent>>(`${root(id)}/events?${query(filters)}`),
    create: (body: BatchCreate, key: string) =>
      post<BatchAction>('/v1/import-batches', body, key),
    upload: (
      id: string,
      file: File,
      key: string,
      onUploadProgress: (loaded: number, total: number | null) => void,
      signal?: AbortSignal,
    ) => {
      const body = new FormData();
      body.append('file', file);
      return request<BatchAction>(`${root(id)}/source-file`, {
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': key },
        signal,
        onUploadProgress,
      });
    },
    precheck: (id: string, version: number, key: string) =>
      post<BatchAction>(
        `${root(id)}/precheck`,
        { preview_version: version } satisfies Schemas['ImportPrecheck'],
        key,
      ),
    confirm: (id: string, body: ConfirmInput, key: string) =>
      post<BatchAction>(`${root(id)}/confirm`, body, key),
    cancel: (id: string, key: string) =>
      post<BatchAction>(`${root(id)}/cancel`, undefined, key),
    retry: (id: string, key: string) =>
      post<Schemas['ImportRetryResult']>(
        `${root(id)}/retry-failed`,
        { selection: 'retryable_only' } satisfies Schemas['ImportRetry'],
        key,
      ),
    recover: (id: string, reason: string, key: string) =>
      post<BatchAction>(
        `${root(id)}/recover`,
        { reason } satisfies Schemas['ImportRecover'],
        key,
      ),
    generateErrorFile: (
      id: string,
      version: number,
      format: Schemas['ImportErrorFileCreate']['format'],
      key: string,
    ) =>
      post<Schemas['ImportErrorFileAction']>(
        `${root(id)}/error-file`,
        {
          format,
          preview_version: version,
        } satisfies Schemas['ImportErrorFileCreate'],
        key,
      ),
    errorFile: (id: string) =>
      request<ErrorFile>(`${root(id)}/artifacts/error-file`),
    download: (id: string, generation: number) =>
      request<Download>(
        `${root(id)}/artifacts/error-file/download?generation=${generation}`,
        { responseType: 'download' },
      ),
  };
}
export type ImportsApi = ReturnType<typeof createImportsApi>;
export function saveFile(file: Download) {
  const url = URL.createObjectURL(file.blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = file.fileName;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
