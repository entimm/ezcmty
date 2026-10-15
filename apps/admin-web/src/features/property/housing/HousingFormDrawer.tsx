import { useId, type ReactNode } from 'react';
import { Button, Drawer, Form, Space } from 'antd';
import { OperationError } from '../../../components/AdminFeedback';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import { applyFormErrors } from '../../../shared/form-utils';
import { ApiError } from '../../../shared/request-client';
import { useHousingOperation } from './hooks';

export function HousingFormDrawer<T extends object>({
  title,
  initialValues,
  fields,
  save,
  done,
  children,
}: {
  title: string;
  initialValues?: Partial<T>;
  fields: string[];
  save: (values: T) => Promise<unknown>;
  done: () => void;
  children: ReactNode;
}) {
  const [form] = Form.useForm<T>();
  const id = useId();
  const operation = useHousingOperation();
  const dirty = useDirtyForm();
  const close = () => {
    if (!operation.isPending) dirty.close(done);
  };
  return (
    <Drawer open title={title} size={600} destroyOnHidden onClose={close}>
      <OperationError error={operation.error} />
      <Form
        form={form}
        name={`housing-${id}`}
        autoComplete="off"
        layout="vertical"
        initialValues={initialValues}
        disabled={operation.isPending}
        onValuesChange={dirty.changed}
        onFinish={async (values: T) => {
          if (operation.isPending) return;
          try {
            await operation.mutateAsync({ run: () => save(values) });
            form.resetFields();
            dirty.reset();
            operation.reset();
            done();
          } catch (error) {
            applyFormErrors(form, error, fields);
            if (
              error instanceof ApiError &&
              error.status === 422 &&
              Array.isArray(error.problem?.errors)
            ) {
              for (const issue of error.problem.errors) {
                if (
                  issue &&
                  typeof issue === 'object' &&
                  'location' in issue &&
                  Array.isArray(issue.location)
                ) {
                  const location = issue.location.slice(
                    issue.location[0] === 'body' ? 1 : 0,
                  );
                  if (
                    location[0] === 'owners' &&
                    typeof location[1] === 'number' &&
                    ['name', 'phone'].includes(location[2])
                  )
                    form.setFields([
                      {
                        name: location,
                        errors: ['请检查该业主字段的格式或长度'],
                      },
                    ]);
                }
              }
            }
          }
        }}
      >
        {children}
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
    </Drawer>
  );
}
