import { Alert, Button, Empty, Result } from 'antd';
import { ApiError } from '../shared/request-client';

export function ReadError({
  retry,
  error,
}: {
  retry: () => void;
  error?: unknown;
}) {
  return (
    <Result
      status="warning"
      title={
        error instanceof ApiError && error.status === 404
          ? '记录不存在'
          : '读取失败，请重试'
      }
      extra={<Button onClick={retry}>重试</Button>}
    />
  );
}
export function OperationError({ error }: { error: unknown }) {
  if (!error || (error instanceof DOMException && error.name === 'AbortError'))
    return null;
  const uncertain = !(error instanceof ApiError) || error.status >= 500;
  return (
    <Alert
      style={{ marginBottom: 16 }}
      showIcon
      type="error"
      title={error instanceof ApiError ? error.message : '请求未完成'}
      description={
        uncertain
          ? '写入结果可能不确定，请刷新核实后再操作。'
          : error instanceof ApiError && error.retryAfter
            ? `请按服务端提示等待：${error.retryAfter}`
            : undefined
      }
    />
  );
}
export function ListEmpty({ filtered }: { filtered: boolean }) {
  return (
    <Empty
      description={filtered ? '没有匹配的记录，请调整查询条件' : '暂无记录'}
    />
  );
}
