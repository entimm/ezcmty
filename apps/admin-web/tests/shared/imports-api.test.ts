import { describe, expect, it, vi } from 'vitest';
import { createImportsApi } from '../../src/shared/imports/api';
import type { AdminRequest, RequestOptions } from '../../src/shared/request';
function transport() {
  const call = vi
    .fn<(path: string, options?: RequestOptions) => Promise<unknown>>()
    .mockResolvedValue({});
  return { call, api: createImportsApi(call as AdminRequest) };
}
describe('导入任务契约保护', () => {
  it('确认保存已发布预览身份与显式部分执行和警告策略，不自行推导', async () => {
    const { call, api } = transport();
    const body = {
      preview_version: 3,
      preview_fingerprint: 'a'.repeat(64),
      apply_policy: 'valid_rows_only' as const,
      include_warning_rows: false,
    };
    await api.confirm('batch-id', body, 'fixed-confirm-key');
    const [path, options] = call.mock.calls[0];
    expect(path).toBe('/v1/import-batches/batch-id/confirm');
    expect(JSON.parse(String(options?.body))).toEqual(body);
    expect(new Headers(options?.headers).get('Idempotency-Key')).toBe(
      'fixed-confirm-key',
    );
  });
  it('失败重跑只请求安全失败行，不继承原确认策略或自动确认新批次', async () => {
    const { call, api } = transport();
    await api.retry('source-batch', 'retry-key');
    expect(call).toHaveBeenCalledTimes(1);
    expect(call.mock.calls[0][0]).toBe(
      '/v1/import-batches/source-batch/retry-failed',
    );
    expect(JSON.parse(String(call.mock.calls[0][1]?.body))).toEqual({
      selection: 'retryable_only',
    });
  });
  it('上传只发送file字段并转交真实进度回调和固定幂等键', async () => {
    const { call, api } = transport();
    const file = new File(['楼栋,房号\n1栋,0101'], '房屋.csv', {
      type: 'text/csv',
    });
    const progress = vi.fn();
    await api.upload('draft', file, 'upload-key', progress);
    const options = call.mock.calls[0][1];
    expect(options?.body).toBeInstanceOf(FormData);
    expect([...(options?.body as FormData).keys()]).toEqual(['file']);
    expect((options?.body as FormData).get('file')).toBe(file);
    expect(options?.onUploadProgress).toBe(progress);
    expect(new Headers(options?.headers).has('Content-Type')).toBe(false);
  });
  it('问题文件下载锁定服务端代次，不请求公开下载地址', async () => {
    const { call, api } = transport();
    await api.download('batch', 7);
    expect(call).toHaveBeenCalledWith(
      '/v1/import-batches/batch/artifacts/error-file/download?generation=7',
      { responseType: 'download' },
    );
  });
});
