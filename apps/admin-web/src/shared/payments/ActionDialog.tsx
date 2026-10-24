import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Checkbox, Form, Input, Modal, Space } from 'antd';
import { ApiError } from '../request';
import { ErrorNotice } from '../imports/presentation';
export interface FundsAction {
  kind: 'recover' | 'recheck' | 'difference' | 'external';
  id: string;
  token: string;
  label: string;
}
export function ActionDialog({
  action,
  submit,
  close,
  setDirty,
  verify,
}: {
  action: FundsAction;
  submit: (reason: string, evidence: string) => Promise<unknown>;
  close: () => void;
  setDirty: (value: boolean) => void;
  verify: () => Promise<unknown>;
}) {
  const { message } = App.useApp();
  const [reason, setReason] = useState('');
  const [evidence, setEvidence] = useState('');
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [discard, setDiscard] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const lock = useRef(false);
  const dirty = !!reason.trim() || !!evidence.trim() || ack;
  useEffect(() => {
    setDirty(dirty);
    if (!dirty) setDiscard(false);
    return () => setDirty(false);
  }, [dirty, setDirty]);
  const requestClose = () => {
    if (busy) return;
    if (dirty) setDiscard(true);
    else close();
  };
  async function save() {
    if (
      lock.current ||
      !reason.trim() ||
      (action.kind === 'external' && (!evidence.trim() || !ack))
    )
      return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      await submit(reason.trim(), evidence.trim());
      message.info(
        action.kind === 'external'
          ? '已记录外部处置，资金事实仍需独立核实'
          : '任务已安排，请查看实际处理结果',
      );
      setDirty(false);
      close();
      await verify();
    } catch (e) {
      setError(e);
      if (
        !(e instanceof ApiError) ||
        e.status === 0 ||
        e.status >= 500 ||
        e.status === 409
      ) {
        setUncertain(true);
        await verify();
      }
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      title={
        action.kind === 'external'
          ? '记录外部处置'
          : action.kind === 'recheck'
            ? '重新核对原批次'
            : '恢复原业务流程'
      }
      width={620}
      onCancel={requestClose}
      mask={{ closable: !busy }}
      keyboard={!busy}
      closable={!busy}
      footer={
        <Space>
          <Button disabled={busy} onClick={requestClose}>
            取消
          </Button>
          <Button
            type="primary"
            loading={busy}
            disabled={
              uncertain ||
              !reason.trim() ||
              (action.kind === 'external' && (!evidence.trim() || !ack))
            }
            onClick={() => void save()}
          >
            {action.kind === 'external'
              ? '记录外部处置'
              : action.kind === 'recheck'
                ? '安排重新核对'
                : '安排恢复任务'}
          </Button>
        </Space>
      }
    >
      {discard && (
        <Alert
          style={{ marginBottom: 20 }}
          type="warning"
          showIcon
          title="有未保存的修改"
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
                  close();
                }}
              >
                放弃修改
              </Button>
            </Space>
          }
        />
      )}
      <Alert
        style={{ marginBottom: 20 }}
        type="warning"
        showIcon
        title={
          action.kind === 'external'
            ? '只记录已核实结论，不改写支付、入账、分账、解冻或支付占用'
            : '按原业务单核实与恢复，不指定成功、不新建替代资金操作'
        }
        description={
          action.kind === 'external'
            ? '保存成功只表示处置结论已记录；同一问题再次出现时会重新打开。'
            : '受理成功不代表资金成功，请等待可信渠道查询及实际处理结果。'
        }
      />
      <div style={{ marginBottom: 20, color: '#64748b' }}>
        目标：{action.label}
      </div>
      <ErrorNotice error={error} />
      {uncertain && (
        <Alert
          style={{ marginBottom: 20 }}
          type="warning"
          showIcon
          title="提交结果待核实或记录已变化"
          description="已刷新原记录。请核对详情与审计，关闭后重新判断是否需要操作；不会自动换令牌重试。"
          action={<Button onClick={() => void verify()}>核实最新结果</Button>}
        />
      )}
      <Form layout="vertical" disabled={busy || uncertain}>
        <Form.Item
          label={action.kind === 'external' ? '处置原因与结论' : '操作原因'}
          required
        >
          <Input.TextArea
            aria-label={
              action.kind === 'external' ? '处置原因与结论' : '操作原因'
            }
            maxLength={1000}
            showCount
            rows={4}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </Form.Item>
        {action.kind === 'external' && (
          <>
            <Form.Item label="已核实的外部工单 / 凭证引用" required>
              <Input
                aria-label="已核实的外部工单 / 凭证引用"
                maxLength={256}
                value={evidence}
                onChange={(event) => setEvidence(event.target.value)}
              />
            </Form.Item>
            <Checkbox
              checked={ack}
              onChange={(event) => setAck(event.target.checked)}
            >
              我已核实外部依据，确认该操作只记录差异处置。
            </Checkbox>
          </>
        )}
      </Form>
    </Modal>
  );
}
