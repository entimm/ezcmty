import {
  useCallback,
  useEffect,
  useId,
  useRef,
  type ReactNode,
  type RefObject,
} from 'react';
import { Button, Drawer, Form, Space, Spin, type FormInstance } from 'antd';
import { OperationError, ReadError } from '../../../components/AdminFeedback';
import { applyFormErrors } from '../../../shared/form-utils';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import { usePropertyOnboardingOperation } from './hooks';

function EditorForm<T extends object>({
  initialValues,
  fields,
  children,
  save,
  done,
  closeRef,
  security,
}: {
  initialValues?: Partial<T>;
  fields: string[];
  children: (form: FormInstance<T>) => ReactNode;
  save: (values: T) => Promise<unknown>;
  done: () => void;
  closeRef: RefObject<() => void>;
  security?: boolean;
}) {
  const [form] = Form.useForm<T>();
  const formId = useId();
  const operation = usePropertyOnboardingOperation();
  const dirty = useDirtyForm();
  const close = useCallback(() => {
    if (!operation.isPending) dirty.close(done);
  }, [operation.isPending, dirty, done]);
  useEffect(() => {
    closeRef.current = close;
  }, [close, closeRef]);
  return (
    <>
      <OperationError error={operation.error} />
      <Form
        name={`property-editor-${formId}`}
        form={form}
        layout="vertical"
        initialValues={initialValues}
        disabled={operation.isPending}
        onValuesChange={dirty.changed}
        onFinish={async (values: T) => {
          if (operation.isPending) return;
          try {
            await operation.mutateAsync({ run: () => save(values), security });
            form.resetFields();
            dirty.reset();
            operation.reset();
            done();
          } catch (error) {
            applyFormErrors(form, error, fields);
          }
        }}
      >
        {children(form)}
        <Space>
          <Button
            type="primary"
            htmlType="submit"
            loading={operation.isPending}
          >
            保存
          </Button>
          <Button onClick={close}>取消</Button>
        </Space>
      </Form>
    </>
  );
}

export function PropertyFormDrawer<T extends object>({
  title,
  loading,
  error,
  retry,
  ...formProps
}: {
  title: string;
  loading?: boolean;
  error?: unknown;
  retry?: () => void;
  initialValues?: Partial<T>;
  fields: string[];
  children: (form: FormInstance<T>) => ReactNode;
  save: (values: T) => Promise<unknown>;
  done: () => void;
  security?: boolean;
}) {
  const closeRef = useRef(formProps.done);
  return (
    <Drawer
      open
      title={title}
      size={520}
      destroyOnHidden
      onClose={() => closeRef.current()}
    >
      {loading ? (
        <Spin />
      ) : error ? (
        <ReadError error={error} retry={retry ?? (() => {})} />
      ) : (
        <EditorForm {...formProps} closeRef={closeRef} />
      )}
    </Drawer>
  );
}
