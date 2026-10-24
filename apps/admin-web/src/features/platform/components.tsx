import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Avatar,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Result,
  Select,
  Space,
  Spin,
  type FormInstance,
} from 'antd';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useAdmin } from '../../shared/context';
import { hasFormChanges } from '../../shared/forms';
import { ApiError } from '../../shared/request';
import {
  createPlatformApi,
  type Company,
  type Filters,
  type Page,
} from './api';

export function usePlatformApi() {
  const { request, scope } = useAdmin();
  if (scope !== 'platform') throw new Error('平台业务只能在平台后台运行');
  return useMemo(() => createPlatformApi(request), [request]);
}

export function time(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return '—';
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}
export function errorText(error: unknown) {
  if (error instanceof TypeError)
    return '网络连接中断。请检查网络；提交操作请先刷新列表核实结果，再决定是否重试。';
  return error instanceof Error ? error.message : '操作失败，请稍后重试';
}
export function Person({ name, sub }: { name: string; sub: string }) {
  return (
    <Space size={10}>
      <Avatar
        size={34}
        style={{ background: '#edf2ff', color: '#4263ce', fontSize: 13 }}
      >
        {name.slice(-2)}
      </Avatar>
      <div>
        <div style={{ fontWeight: 600 }}>{name}</div>
        <div className="muted small">{sub}</div>
      </div>
    </Space>
  );
}
export function ReadState({
  error,
  loading,
  retry,
  children,
}: {
  error?: unknown;
  loading?: boolean;
  retry: () => void;
  children?: ReactNode;
}) {
  if (error instanceof ApiError && error.status === 403)
    return (
      <Result
        status="403"
        title="暂无访问权限"
        subTitle="请联系管理员确认当前账号的授权范围。"
      />
    );
  if (error instanceof ApiError && error.status === 404)
    return (
      <Result
        status="404"
        title="记录不存在"
        subTitle="记录可能已变更，请返回列表重新查询。"
      />
    );
  if (error)
    return (
      <Alert
        type="error"
        showIcon
        title="数据加载失败"
        description={errorText(error)}
        action={
          <Button icon={<ReloadOutlined />} onClick={retry}>
            重试
          </Button>
        }
      />
    );
  if (loading)
    return (
      <div style={{ padding: 72, textAlign: 'center' }}>
        <Spin description="正在加载…" />
      </div>
    );
  return <>{children}</>;
}
export const emptyList = (
  <Empty
    image={Empty.PRESENTED_IMAGE_SIMPLE}
    description="暂无记录或没有符合条件的结果"
  />
);

export function usePlatformWrite() {
  const queryClient = useQueryClient();
  const { refreshSession } = useAdmin();
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const run = async <T,>(operation: () => Promise<T>, security = false) => {
    if (lock.current) throw new Error('操作正在提交，请稍候');
    lock.current = true;
    setBusy(true);
    try {
      const result = await operation();
      await queryClient.invalidateQueries({ queryKey: ['platform'] });
      if (security) await refreshSession();
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409)
        await queryClient.invalidateQueries({ queryKey: ['platform'] });
      throw error;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return { run, busy };
}

export function ListFilter({
  value,
  onSearch,
  onReset,
  placeholder,
  fieldOptions,
  children,
}: {
  value: Record<string, string>;
  onSearch: (filters: Record<string, string | undefined>) => void;
  onReset: () => void;
  placeholder: string;
  fieldOptions?: { value: string; label: string }[];
  children?: ReactNode;
}) {
  const defaultField = fieldOptions?.[0]?.value;
  const [search, setSearch] = useState(value.search || '');
  const [enabled, setEnabled] = useState<string | undefined>(value.enabled);
  const [field, setField] = useState(value.field || defaultField);
  useEffect(() => {
    setSearch(value.search || '');
    setEnabled(value.enabled);
    setField(value.field || defaultField);
  }, [value.search, value.enabled, value.field, defaultField]);
  const submit = () =>
    onSearch({ search: search.trim() || undefined, enabled, field });
  return (
    <div className="filter-bar">
      {fieldOptions && (
        <Select
          aria-label="搜索字段"
          style={{ width: 118 }}
          value={field}
          options={fieldOptions}
          onChange={setField}
        />
      )}
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder={placeholder}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        onPressEnter={submit}
        style={{ width: 240 }}
      />
      <Select
        allowClear
        aria-label="状态"
        placeholder="全部状态"
        value={enabled}
        onChange={setEnabled}
        style={{ width: 140 }}
        options={[
          { value: 'true', label: '启用' },
          { value: 'false', label: '已停用' },
        ]}
      />
      {children}
      <div className="filter-actions">
        <Button type="primary" onClick={submit}>
          查询
        </Button>
        <Button
          onClick={() => {
            setSearch('');
            setEnabled(undefined);
            onReset();
          }}
        >
          重置
        </Button>
      </div>
    </div>
  );
}

export function CompanyPicker({
  value,
  onChange,
  selected,
}: {
  value?: string;
  onChange?: (value: string | undefined) => void;
  selected?: Company;
}) {
  const api = usePlatformApi();
  const { can } = useAdmin();
  const [search, setSearch] = useState('');
  const query = useQuery({
    queryKey: ['platform', 'company-options', search],
    queryFn: () =>
      api.companies({ name: search || undefined, page: 1, page_size: 100 }),
    enabled: can('property.company.read'),
  });
  const options = new Map(
    (query.data?.items ?? []).map((company) => [company.id, company]),
  );
  if (selected) options.set(selected.id, selected);
  return (
    <>
      <Select
        allowClear
        showSearch
        filterOption={false}
        placeholder="选择物业公司"
        aria-label="所属物业公司"
        value={value}
        onChange={onChange}
        onSearch={setSearch}
        loading={query.isFetching}
        options={[...options.values()].map((company) => ({
          value: company.id,
          label: company.name + (company.enabled ? '' : '（公司停用）'),
        }))}
        style={{ minWidth: 230 }}
        notFoundContent={
          query.isError ? (
            '公司加载失败，请重试'
          ) : query.isFetching ? (
            <Spin size="small" />
          ) : (
            '未找到公司'
          )
        }
      />
      <span className="sr-only">
        {query.data && query.data.total > 100
          ? '请搜索公司名称以缩小选择范围'
          : ''}
      </span>
      {query.isError && (
        <Button size="small" onClick={() => void query.refetch()}>
          重试
        </Button>
      )}
    </>
  );
}

export function PlatformFormDialog({
  title,
  initialValues,
  onClose,
  onSubmit,
  render,
  width = 540,
  okText = '保存',
}: {
  title: string;
  initialValues: Record<string, unknown>;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => Promise<void>;
  render: (form: FormInstance, changed: () => void) => ReactNode;
  width?: number;
  okText?: string;
}) {
  const [form] = Form.useForm();
  const { setDirty } = useAdmin();
  const baseline = useRef(initialValues);
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false),
    [discard, setDiscard] = useState(false),
    [error, setError] = useState<unknown>();
  const changed = () => {
    const dirty = hasFormChanges(form.getFieldsValue(true), baseline.current);
    setDirty(dirty);
    if (!dirty) setDiscard(false);
  };
  useEffect(() => {
    setDirty(false);
    return () => setDirty(false);
  }, [setDirty]);
  const close = () => {
    if (submitting.current) return;
    if (hasFormChanges(form.getFieldsValue(true), baseline.current))
      setDiscard(true);
    else {
      setDirty(false);
      onClose();
    }
  };
  return (
    <Modal
      open
      title={title}
      width={width}
      onCancel={close}
      onOk={() => form.submit()}
      confirmLoading={busy}
      okText={okText}
      cancelText="取消"
      closable={!busy}
      mask={{ closable: !busy }}
      keyboard={!busy}
      cancelButtonProps={{ disabled: busy }}
      destroyOnHidden
    >
      {discard && (
        <Alert
          type="warning"
          showIcon
          title="有未保存的修改"
          description="继续编辑，或放弃本次修改后关闭。"
          action={
            <Space>
              <Button size="small" onClick={() => setDiscard(false)}>
                继续编辑
              </Button>
              <Button
                danger
                size="small"
                onClick={() => {
                  setDirty(false);
                  onClose();
                }}
              >
                放弃修改
              </Button>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}
      {!!error && (
        <Alert
          type="error"
          showIcon
          title="保存失败"
          description={errorText(error)}
          style={{ marginBottom: 16 }}
        />
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        disabled={busy}
        onValuesChange={changed}
        style={{ paddingTop: 14 }}
        onFinish={async (values) => {
          if (submitting.current) return;
          submitting.current = true;
          setBusy(true);
          setError(undefined);
          try {
            await onSubmit(values);
            setDirty(false);
            onClose();
          } catch (reason) {
            setError(reason);
            if (
              reason instanceof ApiError &&
              reason.status === 422 &&
              Array.isArray(reason.problem?.errors)
            ) {
              for (const issue of reason.problem.errors)
                if (
                  issue &&
                  typeof issue === 'object' &&
                  'location' in issue &&
                  Array.isArray(issue.location)
                ) {
                  const name =
                    issue.location[issue.location[0] === 'body' ? 1 : 0];
                  if (typeof name === 'string')
                    form.setFields([
                      { name, errors: ['请检查此项的格式、长度或可用性'] },
                    ]);
                }
            }
          } finally {
            submitting.current = false;
            setBusy(false);
          }
        }}
      >
        {render(form, changed)}
      </Form>
    </Modal>
  );
}
export function PasswordFields({ form }: { form: FormInstance }) {
  return (
    <>
      <Form.Item
        name="password"
        label="临时密码"
        rules={[
          { required: true, message: '请输入临时密码' },
          { min: 12, max: 128, message: '请输入 12–128 位密码' },
        ]}
      >
        <Input.Password
          autoComplete="new-password"
          placeholder="至少 12 位，建议组合多种字符"
        />
      </Form.Item>
      <Form.Item
        name="confirm_password"
        label="确认临时密码"
        dependencies={['password']}
        rules={[
          { required: true, message: '请再次输入临时密码' },
          {
            validator: (_, value) =>
              value === form.getFieldValue('password')
                ? Promise.resolve()
                : Promise.reject(new Error('两次密码不一致')),
          },
        ]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
    </>
  );
}

export function pagination<T>(
  data: Page<T> | undefined,
  filters: Filters,
  change: (page: number) => void,
) {
  return {
    current: Number(filters.page) || 1,
    pageSize: 8,
    total: data?.total ?? 0,
    showSizeChanger: false,
    showTotal: (total: number) => `共 ${total} 条`,
    onChange: change,
  };
}
