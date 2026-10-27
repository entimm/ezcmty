import { DatePicker } from './DatePicker';
import {
  Alert,
  Button,
  Empty,
  Input,
  Select,
  Space,
  Tag,
  Skeleton,
  Result,
} from 'antd';
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';
import { ApiError } from './request';
export function money(value: number | null | undefined) {
  return value == null
    ? '待核对'
    : `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
export function PageHeader({
  title,
  description,
  extra,
  back,
}: {
  title: ReactNode;
  description?: ReactNode;
  extra?: ReactNode;
  back?: () => void;
}) {
  return (
    <div className="page-heading">
      <div>
        {back && (
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={back}
            className="back-button"
          >
            返回列表
          </Button>
        )}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      <Space wrap>{extra}</Space>
    </div>
  );
}
export function Panel({
  title,
  extra,
  children,
  className = '',
}: {
  title?: ReactNode;
  extra?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || extra) && (
        <div className="panel-heading">
          <h3>{title}</h3>
          <div>{extra}</div>
        </div>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}
export function Status({
  children,
  color,
}: {
  children: ReactNode;
  color?: string;
}) {
  const text = String(children);
  const tone =
    color ||
    (text.match(/成功|启用|通过|已缴清|已解决|正常|已入账|可收款|已完成|有效/)
      ? 'green'
      : text.match(/异常|失败|拒绝|错误|已停用|驳回/)
        ? 'red'
        : text.match(/待|处理中|部分|警告/)
          ? 'orange'
          : 'default');
  return (
    <Tag color={tone} className="status-tag">
      <span className="status-dot" />
      {children}
    </Tag>
  );
}
export function DetailGrid({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <div className="detail-grid">
      {items.map(([label, value], i) => (
        <div key={i}>
          <span>{label}</span>
          <strong>{value ?? '—'}</strong>
        </div>
      ))}
    </div>
  );
}
export const tablePagination = {
  pageSize: 20,
  showSizeChanger: true,
  showTotal: (total: number) => `共 ${total} 条`,
};
export function ReadError({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  if (error == null) return null;
  if (error instanceof DOMException && error.name === 'AbortError') return null;
  return (
    <Alert
      type="error"
      showIcon
      title={
        error instanceof ApiError && error.status === 403
          ? '当前账号无权读取此数据'
          : '数据暂时读取失败'
      }
      description={
        <>
          {error instanceof Error ? error.message : '请稍后重试'}
          {error instanceof ApiError && error.requestId && (
            <details>
              <summary>请求标识</summary>
              {error.requestId}
            </details>
          )}
        </>
      }
      action={
        retry && (
          <Button size="small" icon={<ReloadOutlined />} onClick={retry}>
            重试
          </Button>
        )
      }
      style={{ marginBottom: 20 }}
    />
  );
}
export function Loading() {
  return (
    <Panel>
      <Skeleton active paragraph={{ rows: 7 }} />
    </Panel>
  );
}
export function NoAccess({ back }: { back?: () => void }) {
  return (
    <Panel>
      <Result
        status="403"
        title="暂无访问权限"
        subTitle="请联系管理员核实当前账号权限。"
        extra={back && <Button onClick={back}>返回工作概览</Button>}
      />
    </Panel>
  );
}
export function NotFound({ back }: { back?: () => void }) {
  return (
    <Panel>
      <Result
        status="404"
        title="页面或记录不存在"
        subTitle="请核对地址或返回当前后台继续工作。"
        extra={back && <Button onClick={back}>返回工作概览</Button>}
      />
    </Panel>
  );
}
export function ListEmpty({ filtered = false }: { filtered?: boolean }) {
  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        filtered ? '暂无匹配结果，请调整筛选条件' : '当前范围暂无记录'
      }
    />
  );
}
export function FilterBar({
  search,
  setSearch,
  placeholder = '搜索名称、编号',
  status,
  setStatus,
  statuses = [],
  dates = false,
  children,
  onSearch,
  onReset,
}: {
  search?: string;
  setSearch?: (v: string) => void;
  placeholder?: string;
  status?: string;
  setStatus?: (v: string | undefined) => void;
  statuses?: string[];
  dates?: boolean;
  children?: ReactNode;
  onSearch?: () => void;
  onReset?: () => void;
}) {
  return (
    <div className="filter-bar">
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder={placeholder}
        value={search}
        onChange={(e) => setSearch?.(e.target.value)}
        onPressEnter={onSearch}
        style={{ width: 240 }}
      />
      {statuses.length > 0 && (
        <Select
          allowClear
          placeholder="全部状态"
          value={status}
          onChange={setStatus}
          options={statuses.map((value) => ({ value, label: value }))}
          style={{ width: 140 }}
        />
      )}
      {dates && <DatePicker.RangePicker />}
      {children}
      <div className="filter-actions">
        <Button type="primary" onClick={onSearch}>
          查询
        </Button>
        <Button
          onClick={() => {
            setSearch?.('');
            setStatus?.(undefined);
            onReset?.();
          }}
        >
          重置
        </Button>
      </div>
    </div>
  );
}
export function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob),
    link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
