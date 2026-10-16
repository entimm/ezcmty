import { useState } from 'react';
import { Alert, Button, Drawer, Form, Input, Space } from 'antd';
import { OperationError } from '../../../components/AdminFeedback';
import { applyFormErrors } from '../../../shared/form-utils';
import { useDirtyForm } from '../../../shared/hooks/use-dirty-form';
import { ApiError } from '../../../shared/request-client';
import { useClaimDecision, useHouseClaimsApi } from './hooks';
import type { Claim, HouseBinding } from './api';

type Action =
  | { kind: 'review'; record: Claim; decision: 'approved' | 'rejected' }
  | { kind: 'revoke'; record: HouseBinding };

export function DecisionDrawer({
  action,
  done,
}: {
  action: Action;
  done: () => void;
}) {
  const api = useHouseClaimsApi();
  const operation = useClaimDecision();
  const dirty = useDirtyForm();
  const [form] = Form.useForm<{ reason?: string }>();
  const [locked, setLocked] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<unknown>();
  const revoke = action.kind === 'revoke';
  const approve = action.kind === 'review' && action.decision === 'approved';
  const required =
    revoke ||
    !approve ||
    (action.kind === 'review' && action.record.match_status === 'unmatched');
  const title = revoke
    ? '撤销房屋绑定'
    : approve
      ? '通过认领申请'
      : '驳回认领申请';
  const close = () => {
    if (!operation.isPending && !checking) dirty.close(done);
  };
  const conflict =
    operation.error instanceof ApiError && operation.error.status === 409;
  return (
    <Drawer
      open
      title={title}
      size={560}
      onClose={close}
      maskClosable={false}
      destroyOnHidden
    >
      <p>
        {action.record.house_label_snapshot} · {action.record.applicant_name}
      </p>
      <Alert
        style={{ marginBottom: 16 }}
        showIcon
        type={approve ? 'info' : 'warning'}
        title={
          revoke
            ? '撤销后该居民将失去此房屋的使用权限，再次认领需要重新审批。'
            : approve
              ? '确认已核实申请人的业主身份。通过后立即授予房屋使用权限。'
              : '请说明驳回原因，居民可据此更正后重新申请。'
        }
        description={
          approve &&
          action.kind === 'review' &&
          action.record.match_status === 'unmatched'
            ? '申请时姓名和手机号未匹配。核实通过后可独立批准，业主档案请另行维护。'
            : undefined
        }
      />
      <OperationError error={operation.error} />
      {locked && (
        <Alert
          showIcon
          type="warning"
          style={{ marginBottom: 16 }}
          title={
            conflict
              ? '申请或绑定状态已变化，请刷新核实结果。'
              : '操作结果需要核实，请先刷新查看当前状态。'
          }
        />
      )}
      <OperationError error={checkError} />
      <Form
        form={form}
        layout="vertical"
        autoComplete="off"
        disabled={operation.isPending || locked || checking}
        onValuesChange={dirty.changed}
        onFinish={async (values) => {
          if (operation.isPending || locked || checking) return;
          const reason = values.reason?.trim() || undefined;
          try {
            await operation.mutateAsync(() =>
              action.kind === 'review'
                ? api.review(action.record.id, {
                    expected_row_version: action.record.row_version,
                    decision: action.decision,
                    reason,
                  })
                : api.revoke(action.record.id, {
                    expected_row_version: action.record.row_version,
                    reason: reason!,
                  }),
            );
            dirty.reset();
            done();
          } catch (error) {
            applyFormErrors(form, error, ['reason']);
            if (
              !(error instanceof ApiError) ||
              error.status >= 500 ||
              error.status === 409
            )
              setLocked(true);
          }
        }}
      >
        <Form.Item
          name="reason"
          label={revoke ? '撤销原因' : '审核说明'}
          rules={[
            { required, whitespace: true, message: '请填写原因' },
            { max: 1000 },
          ]}
        >
          <Input.TextArea
            rows={4}
            maxLength={1000}
            showCount
            placeholder={
              required ? '请填写核实过程或处理原因' : '可填写审核说明'
            }
          />
        </Form.Item>
        <Space>
          <Button
            htmlType="submit"
            type="primary"
            danger={!approve}
            loading={operation.isPending}
            disabled={locked || checking}
          >
            确认{revoke ? '撤销' : approve ? '通过' : '驳回'}
          </Button>
          <Button onClick={close} disabled={operation.isPending || checking}>
            关闭
          </Button>
        </Space>
      </Form>
      {locked && (
        <Button
          style={{ marginTop: 16 }}
          loading={checking}
          onClick={async () => {
            setChecking(true);
            setCheckError(undefined);
            try {
              if (action.kind === 'review') await api.claim(action.record.id);
              else await api.binding(action.record.id);
              await operation.invalidate();
              dirty.reset();
              done();
            } catch (error) {
              setCheckError(error);
            } finally {
              setChecking(false);
            }
          }}
        >
          刷新核实结果
        </Button>
      )}
    </Drawer>
  );
}
