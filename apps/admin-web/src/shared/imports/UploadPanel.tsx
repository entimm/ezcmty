import { Alert, Button, Card, Space, Spin, Typography, Upload } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { OperationError } from '../../components/AdminFeedback';
import { useImports, useImportWrite } from './runtime';
export function SourceUpload({
  batchId,
  refresh,
}: {
  batchId: string;
  refresh: () => void;
}) {
  const { api } = useImports(),
    write = useImportWrite(batchId);
  const [file, setFile] = useState<File>(),
    [error, setError] = useState<unknown>(null),
    [transferring, setTransferring] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function upload() {
    if (!file || write.busy) return;
    setError(null);
    setTransferring(true);
    try {
      const digest = await crypto.subtle.digest(
        'SHA-256',
        await file.arrayBuffer(),
      );
      const sha256 = Array.from(new Uint8Array(digest))
        .map((value) => value.toString(16).padStart(2, '0'))
        .join('');
      const previous = write.pending.find((item) => item.action === 'upload');
      if (previous && (previous.body as { sha256: string }).sha256 !== sha256)
        throw new Error(
          '待核实上传必须重新选择相同文件，不能用新文件替换原请求',
        );
      const abort = new AbortController();
      controller.current = abort;
      await write.run('upload', { sha256, size_bytes: file.size }, (key) =>
        api.upload(batchId, file, key, abort.signal, () => {}),
      );
    } catch (reason) {
      setError(reason);
    } finally {
      setTransferring(false);
      refresh();
    }
  }
  return (
    <Card title="上传源文件">
      <Space orientation="vertical" style={{ width: '100%' }}>
        <Typography.Paragraph>
          支持 CSV、XLSX，最大 10 MiB、50,000 数据行、200
          列。服务器完成解析前总行数未知。草稿创建 24 小时后失效。
        </Typography.Paragraph>
        <OperationError error={write.error || error} />
        {error instanceof Error && !(error instanceof DOMException) && (
          <Alert type="error" title={error.message} />
        )}
        {write.pending.some((item) => item.action === 'upload') && (
          <Alert
            type="warning"
            title="上传结果正在核实"
            description="先刷新批次确认是否已接收；仍需上传时选择相同文件，使用原请求键重试。"
          />
        )}
        <Upload.Dragger
          accept=".csv,.xlsx"
          maxCount={1}
          disabled={transferring}
          fileList={
            file
              ? [
                  {
                    uid: 'source',
                    name: file.name,
                    size: file.size,
                    status: 'done',
                  },
                ]
              : []
          }
          beforeUpload={(next) => {
            if (
              !/\.(csv|xlsx)$/i.test(next.name) ||
              next.size > 10485760 ||
              next.size === 0
            ) {
              setError(
                new Error('请选择不超过 10 MiB 的非空 CSV 或 XLSX 文件'),
              );
              return Upload.LIST_IGNORE;
            }
            setFile(next);
            setError(null);
            return false;
          }}
          onRemove={() => {
            setFile(undefined);
            return true;
          }}
        >
          <Typography.Paragraph>拖拽或选择文件</Typography.Paragraph>
        </Upload.Dragger>
        {file && (
          <Typography.Text>
            {file.name} · {(file.size / 1024).toFixed(1)} KiB
          </Typography.Text>
        )}
        {transferring && (
          <Space>
            <Spin size="small" />
            <Typography.Text>文件传输中，等待服务器确认…</Typography.Text>
          </Space>
        )}
        <Space>
          <Button
            type="primary"
            disabled={!file}
            loading={transferring}
            onClick={() => void upload()}
          >
            上传并开始预检
          </Button>
          {transferring && (
            <Button
              onClick={() => {
                controller.current?.abort();
                refresh();
              }}
            >
              停止当前传输
            </Button>
          )}
          <Button onClick={refresh}>核实批次状态</Button>
        </Space>
        <Typography.Text type="secondary">
          停止传输只会中断当前连接；文件可能已被接收。取消整个批次请使用独立取消操作。
        </Typography.Text>
      </Space>
    </Card>
  );
}
