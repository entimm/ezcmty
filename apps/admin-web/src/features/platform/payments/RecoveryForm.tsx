import { useState } from 'react';
import { App, Button, Form, Input, Modal } from 'antd';
import { OperationError } from '../../../components/AdminFeedback';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import type {
  RecoveryAccepted,
  RecoveryInput,
} from '../../../shared/payments/types';
import { usePaymentsOperation } from './hooks';
export function RecoveryForm({
  token,
  submit,
  done,
}: {
  token: string;
  submit: (value: RecoveryInput) => Promise<RecoveryAccepted>;
  done: () => void;
}) {
  const operation = usePaymentsOperation();
  const dirty = useDirtyForm();
  const { message } = App.useApp();
  const [submitted, setSubmitted] = useState(false);
  const [expectedToken] = useState(token);
  return (
    <Modal
      open
      title="恢复原流程"
      onCancel={() => dirty.close(done)}
      footer={null}
      destroyOnHidden
    >
      <OperationError error={operation.error} />
      <p>仅安排原订单核实与正常恢复，任务受理后请查询实际结果。</p>
      <Form
        layout="vertical"
        onValuesChange={dirty.changed}
        onFinish={(values: { reason: string }) =>
          operation.mutate(
            {
              run: () =>
                submit({
                  reason: values.reason.trim(),
                  expected_state_token: expectedToken,
                }),
            },
            {
              onSuccess: () => {
                setSubmitted(true);
                dirty.reset();
                void message.info('任务已安排，请查询实际结果');
                done();
              },
            },
          )
        }
      >
        <Form.Item
          label="恢复原因"
          name="reason"
          rules={[{ required: true, whitespace: true, max: 1000 }]}
        >
          <Input.TextArea rows={3} />
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          loading={operation.isPending}
          disabled={operation.isPending || submitted}
        >
          安排恢复
        </Button>
      </Form>
    </Modal>
  );
}
