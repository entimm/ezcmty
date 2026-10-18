import { useState, type ReactNode } from 'react';
import { Alert, Button, Drawer, Form, Space, type FormInstance } from 'antd';
import { OperationError } from '../../../components/AdminFeedback';
import { applyFormErrors } from '../../../shared/form-utils';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import type { BillSubmission, BillWriteResult } from './api';
import { useBillingWrite, usePendingBills } from './hooks';

export function WriteDrawer<T extends object>({
  title,
  form,
  initialValues,
  prepare,
  done,
  children,
  disabled = false,
}: {
  title: string;
  form: FormInstance<T>;
  initialValues?: Partial<T>;
  prepare: (values: T) => BillSubmission;
  done: (result?: BillWriteResult) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  const operation = useBillingWrite();
  const pending = usePendingBills();
  const dirty = useDirtyForm();
  const [error, setError] = useState<unknown>();
  const [inputError, setInputError] = useState('');
  const close = () => {
    if (!operation.isPending) dirty.close(() => done());
  };
  return (
    <Drawer
      open
      title={title}
      size={680}
      onClose={close}
      destroyOnHidden
      maskClosable={false}
    >
      <OperationError error={error ?? operation.error} />
      {inputError && (
        <Alert
          type="error"
          showIcon
          title={inputError}
          style={{ marginBottom: 16 }}
        />
      )}
      {!!pending.length && (
        <Alert
          style={{ marginBottom: 16 }}
          type="warning"
          showIcon
          title="有待核实操作，请先在页面核实结果"
        />
      )}
      <Form
        form={form}
        initialValues={initialValues}
        layout="vertical"
        autoComplete="off"
        disabled={disabled || operation.isPending || !!pending.length}
        onValuesChange={dirty.changed}
        onFinish={async (values: T) => {
          if (disabled || operation.isPending || pending.length) return;
          setError(undefined);
          setInputError('');
          let submission: BillSubmission;
          try {
            submission = prepare(values);
          } catch (caught) {
            setInputError(
              caught instanceof Error ? caught.message : '请核对表单',
            );
            return;
          }
          try {
            const result = await operation.mutateAsync({ submission });
            dirty.reset();
            done(result);
          } catch (caught) {
            setError(caught);
            applyFormErrors(form, caught, Object.keys(values));
          }
        }}
      >
        {children}
        <Space>
          <Button
            htmlType="submit"
            type="primary"
            loading={operation.isPending}
            disabled={disabled || !!pending.length}
          >
            确认保存
          </Button>
          <Button disabled={operation.isPending} onClick={close}>
            关闭
          </Button>
        </Space>
      </Form>
    </Drawer>
  );
}
