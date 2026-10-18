import { useState } from 'react';
import { Alert, App, Button, Checkbox, Form, Input, Modal } from 'antd';
import { OperationError } from '../../../components/AdminFeedback';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import { ApiError } from '../../../shared/request-client';
import type {
  Discrepancy,
  ExternalResolutionInput,
} from '../../../shared/payments/types';
import { usePaymentsOperation } from './hooks';
export function ExternalResolutionForm({
  token,
  submit,
  verify,
  done,
}: {
  token: string;
  submit: (value: ExternalResolutionInput) => Promise<Discrepancy>;
  verify: () => void;
  done: () => void;
}) {
  const operation = usePaymentsOperation();
  const dirty = useDirtyForm();
  const { message } = App.useApp();
  const [uncertain, setUncertain] = useState(false);
  const [expectedToken] = useState(token);
  return (
    <Modal
      open
      title="记录已核实外部处置"
      onCancel={() => dirty.close(done)}
      footer={null}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        title="只记录差异处置与审计，资金事实须通过原业务流程核实。"
      />
      <OperationError error={operation.error} />
      {uncertain && (
        <Alert
          type="warning"
          title="提交结果未知，请先查看差异详情与管理员审计"
          action={<Button onClick={verify}>核实详情与审计</Button>}
        />
      )}
      <Form
        layout="vertical"
        onValuesChange={dirty.changed}
        onFinish={(values: { reason: string; evidence_reference: string }) =>
          operation.mutate(
            {
              run: () =>
                submit({
                  reason: values.reason.trim(),
                  evidence_reference: values.evidence_reference.trim(),
                  expected_state_token: expectedToken,
                }),
            },
            {
              onSuccess: () => {
                dirty.reset();
                void message.success('已记录外部处置');
                done();
              },
              onError: (error) => {
                if (
                  !(error instanceof ApiError) ||
                  error.status >= 500 ||
                  error.status === 0
                ) {
                  setUncertain(true);
                  verify();
                } else if (error.status === 409) {
                  setUncertain(true);
                  verify();
                }
              },
            },
          )
        }
      >
        <Form.Item
          name="reason"
          label="处置原因与结论"
          rules={[{ required: true, whitespace: true, max: 1000 }]}
        >
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item
          name="evidence_reference"
          label="已核实的外部工单／凭证引用"
          rules={[{ required: true, whitespace: true, max: 256 }]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="confirmed"
          valuePropName="checked"
          rules={[
            {
              validator: (_, value: boolean) =>
                value
                  ? Promise.resolve()
                  : Promise.reject(new Error('请先核实外部依据并确认')),
            },
          ]}
        >
          <Checkbox>我已核实外部依据，确认该操作只记录差异处置</Checkbox>
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          loading={operation.isPending}
          disabled={operation.isPending || uncertain}
        >
          记录外部处置
        </Button>
      </Form>
    </Modal>
  );
}
