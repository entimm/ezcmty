import { App } from 'antd';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ActionDialog } from '../../src/shared/payments/ActionDialog';
const action = {
  kind: 'external' as const,
  id: 'difference',
  token: 'frozen-token',
  label: '金额不符 · 差异A',
};
afterEach(cleanup);
function setup(submit = vi.fn().mockResolvedValue({})) {
  const close = vi.fn(),
    verify = vi.fn().mockResolvedValue({}),
    setDirty = vi.fn();
  render(
    <App>
      <ActionDialog
        action={action}
        submit={submit}
        close={close}
        verify={verify}
        setDirty={setDirty}
      />
    </App>,
  );
  return { close, submit, verify, setDirty };
}
describe('资金处置确认与未知结果保护', () => {
  it('空白关闭免确认，有输入时在原弹窗提供放弃选择', () => {
    const { close } = setup();
    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(close).toHaveBeenCalledOnce();
    cleanup();
    const second = setup();
    fireEvent.change(screen.getByRole('textbox', { name: '处置原因与结论' }), {
      target: { value: '已核实' },
    });
    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(second.close).not.toHaveBeenCalled();
    expect(screen.getByText('有未保存的修改')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '放弃修改' }));
    expect(second.close).toHaveBeenCalledOnce();
  });
  it('必须填写原因依据并显式确认，提交中阻止重复操作', async () => {
    let finish: ((value: unknown) => void) | undefined;
    const submit = vi.fn(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    setup(submit);
    const button = screen.getByRole('button', { name: /记录外部处置/ });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole('textbox', { name: '处置原因与结论' }), {
      target: { value: '已核实' },
    });
    fireEvent.change(
      screen.getByRole('textbox', { name: '已核实的外部工单 / 凭证引用' }),
      { target: { value: '工单 123' } },
    );
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(button);
    fireEvent.click(button);
    expect(submit).toHaveBeenCalledOnce();
    await act(async () => finish?.({}));
  });
  it('响应未知后先核实并锁定再次提交，不将资金显示为成功', async () => {
    const { submit, verify } = setup(
      vi.fn().mockRejectedValue(new TypeError('网络中断')),
    );
    fireEvent.change(screen.getByRole('textbox', { name: '处置原因与结论' }), {
      target: { value: '已核实' },
    });
    fireEvent.change(
      screen.getByRole('textbox', { name: '已核实的外部工单 / 凭证引用' }),
      { target: { value: '工单 123' } },
    );
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /记录外部处置/ }));
    await waitFor(() => expect(verify).toHaveBeenCalledOnce());
    expect(screen.getByRole('button', { name: /记录外部处置/ })).toBeDisabled();
    expect(screen.getByText('提交结果待核实或记录已变化')).toBeInTheDocument();
    expect(submit).toHaveBeenCalledOnce();
  });
});
