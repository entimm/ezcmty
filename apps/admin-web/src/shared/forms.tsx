import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from 'react';
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  Modal,
  Space,
  type FormInstance,
} from 'antd';
import type { FormProps } from 'antd';
import { useAdmin } from './context';
function normalize(value: unknown): unknown {
  if (value == null) return null;
  if (typeof value === 'string') return value.trim() || null;
  if (Array.isArray(value)) {
    const items = value.map(normalize);
    return items.length
      ? items.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))
      : null;
  }
  if (typeof value === 'object') {
    if (value instanceof Date) return value.valueOf();
    if ('$isDayjsObject' in value && 'valueOf' in value) return value.valueOf();
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, v]) => [key, normalize(v)]),
    );
  }
  return value;
}
export function hasFormChanges(values: object, initial: object = {}) {
  const before = initial as Record<string, unknown>;
  return Object.entries(values).some(
    ([key, value]) =>
      JSON.stringify(normalize(value)) !==
      JSON.stringify(normalize(before[key])),
  );
}
export function FormDialog<T extends object = Record<string, unknown>>({
  open,
  title,
  width = 600,
  form,
  initialValues,
  onClose,
  onSubmit,
  children,
  busy = false,
  okText = '保存',
  danger = false,
  dialogKey,
  extra,
  layout = 'vertical',
}: {
  open: boolean;
  title: ReactNode;
  width?: number;
  form: FormInstance<T>;
  initialValues?: Partial<T>;
  onClose: () => void;
  onSubmit: (values: T) => Promise<void> | void;
  children: ReactNode;
  busy?: boolean;
  okText?: string;
  danger?: boolean;
  dialogKey?: string;
  extra?: ReactNode;
  layout?: FormProps['layout'];
}) {
  const { setDirty } = useAdmin();
  const initial = useRef<Partial<T>>(initialValues || {}),
    [abandon, setAbandon] = useState(false);
  const latestInitial = useRef(initialValues);
  latestInitial.current = initialValues;
  useEffect(() => {
    if (open) {
      initial.current = latestInitial.current || {};
      form.resetFields();
      form.setFieldsValue(
        initial.current as Parameters<FormInstance<T>['setFieldsValue']>[0],
      );
      setDirty(false);
      setAbandon(false);
    }
    return () => {
      if (open) setDirty(false);
    };
  }, [open, dialogKey, form, setDirty]);
  const close = () => {
    if (busy) return;
    if (hasFormChanges(form.getFieldsValue(), initial.current) && !abandon) {
      setAbandon(true);
      return;
    }
    setDirty(false);
    setAbandon(false);
    onClose();
  };
  return (
    <Modal
      title={title}
      open={open}
      width={width}
      onCancel={close}
      mask={{ closable: !busy }}
      closable={!busy}
      keyboard={!busy}
      destroyOnHidden
      styles={{
        body: {
          maxHeight: 'min(70vh,680px)',
          overflowY: 'auto',
          overflowX: 'hidden',
        },
      }}
      footer={
        <Space>
          <Button onClick={close} disabled={busy}>
            {abandon ? '放弃并关闭' : '取消'}
          </Button>
          <Button
            type="primary"
            danger={danger}
            loading={busy}
            onClick={() =>
              void form
                .validateFields()
                .then(onSubmit)
                .catch(() => undefined)
            }
          >
            {okText}
          </Button>
        </Space>
      }
    >
      {abandon && (
        <Alert
          showIcon
          type="warning"
          title="有尚未保存的内容"
          description="继续填写可保留输入；放弃并关闭将丢弃本次修改。"
          action={
            <Button size="small" onClick={() => setAbandon(false)}>
              继续填写
            </Button>
          }
          style={{ marginBottom: 20 }}
        />
      )}
      {extra}
      <Form
        form={form}
        layout={layout}
        disabled={busy}
        onValuesChange={() => {
          setDirty(hasFormChanges(form.getFieldsValue(), initial.current));
          setAbandon(false);
        }}
      >
        {children}
      </Form>
    </Modal>
  );
}
export const existingPasswordRules = [
  { required: true, message: '请输入密码' },
  { min: 1, max: 128, message: '密码长度为1–128位' },
];
export const newPasswordRules = [
  { required: true, message: '请输入密码' },
  { min: 12, max: 128, message: '密码长度为12–128位' },
  {
    pattern: /^(?![\s\S]*[\r\n])/,
    message: '密码不能包含换行符',
  },
];
export function NewPasswordInput({
  onPaste,
  ...props
}: ComponentProps<typeof Input.Password>) {
  const { message } = App.useApp();
  return (
    <Input.Password
      {...props}
      onPaste={(event) => {
        if (/[\r\n]/.test(event.clipboardData.getData('text/plain'))) {
          event.preventDefault();
          void message.warning('密码不能包含换行符，请粘贴不含换行的内容');
          return;
        }
        onPaste?.(event);
      }}
    />
  );
}
export const loginNameRules = [
  { required: true, message: '请输入登录账号' },
  {
    pattern: /^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$/,
    message: '使用1–64位字母、数字、点、@、下划线或连字符',
  },
];
