import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Form, Modal, Space, type FormInstance } from 'antd';
import { useAdmin } from '../../shared/context';
import { hasFormChanges } from '../../shared/forms';

export function PropertyEditor({
  title,
  form,
  initial = {},
  submit,
  close,
  children,
  width = 600,
  danger = false,
  confirmLabel = '确认保存',
  readOnly = false,
  locked = false,
  extra,
  className,
}: {
  title: string;
  form: FormInstance;
  initial?: Record<string, unknown>;
  submit?: (values: Record<string, unknown>) => Promise<unknown>;
  close: () => void;
  children: ReactNode;
  width?: number;
  danger?: boolean;
  confirmLabel?: string;
  readOnly?: boolean;
  locked?: boolean;
  extra?: ReactNode;
  className?: string;
}) {
  const { setDirty } = useAdmin();
  const baseline = useRef(initial);
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false);
  const [abandon, setAbandon] = useState(false);
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    form.setFieldsValue(baseline.current);
    return () => setDirty(false);
  }, [form, setDirty]);
  const changed = () => {
    setAbandon(false);
    setDirty(
      !readOnly && hasFormChanges(form.getFieldsValue(true), baseline.current),
    );
  };
  const cancel = () => {
    if (busy || locked) return;
    if (
      !readOnly &&
      hasFormChanges(form.getFieldsValue(true), baseline.current) &&
      !abandon
    ) {
      setAbandon(true);
      return;
    }
    setDirty(false);
    close();
  };
  const save = async () => {
    if (busy || submitting.current || locked || !submit) return;
    submitting.current = true;
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      submitting.current = false;
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      await submit(values);
      setDirty(false);
      close();
    } catch (failure) {
      setError(failure);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      title={title}
      width={width}
      className={className}
      onCancel={cancel}
      mask={{ closable: !busy && !locked }}
      keyboard={!busy && !locked}
      closable={!busy && !locked}
      destroyOnHidden
      styles={{
        body: {
          maxHeight: 'min(70vh, 640px)',
          overflowY: 'auto',
          overflowX: 'hidden',
          paddingRight: 4,
        },
      }}
      footer={
        readOnly ? (
          <Button onClick={cancel}>关闭</Button>
        ) : (
          <Space>
            <Button disabled={busy || locked} onClick={cancel}>
              {abandon ? '放弃并关闭' : '取消'}
            </Button>
            <Button
              type="primary"
              danger={danger}
              loading={busy}
              disabled={locked}
              onClick={() => void save()}
            >
              {confirmLabel}
            </Button>
          </Space>
        )
      }
    >
      <div style={{ paddingTop: 14 }}>
        {abandon && (
          <Alert
            showIcon
            type="warning"
            title="有尚未保存的内容"
            description="继续填写可保留输入；选择“放弃并关闭”将丢弃本次修改。"
            action={
              <Button size="small" onClick={() => setAbandon(false)}>
                继续填写
              </Button>
            }
            style={{ marginBottom: 18 }}
          />
        )}
        {error !== undefined && (
          <Alert
            showIcon
            type="error"
            title="操作未完成"
            description={
              error instanceof Error ? error.message : '请核对后重试'
            }
            style={{ marginBottom: 18 }}
          />
        )}
        {extra}
        <Form
          form={form}
          initialValues={baseline.current}
          layout="vertical"
          disabled={busy || locked}
          onValuesChange={changed}
          autoComplete="off"
          style={{ padding: '0 8px' }}
        >
          {children}
        </Form>
      </div>
    </Modal>
  );
}
