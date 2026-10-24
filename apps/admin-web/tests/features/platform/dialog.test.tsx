import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { Form, Input } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import {
  AdminContext,
  type AdminContextValue,
} from '../../../src/shared/context';
import { PlatformFormDialog } from '../../../src/features/platform/components';

function show(
  initialValues: Record<string, unknown> = {},
  onSubmit = vi.fn().mockResolvedValue(undefined),
) {
  const onClose = vi.fn(),
    setDirty = vi.fn();
  const context = { setDirty } as unknown as AdminContextValue;
  render(
    <AdminContext.Provider value={context}>
      <PlatformFormDialog
        title="编辑资料"
        initialValues={initialValues}
        onClose={onClose}
        onSubmit={onSubmit}
        render={() => (
          <Form.Item name="name" label="名称">
            <Input />
          </Form.Item>
        )}
      />
    </AdminContext.Provider>,
  );
  return { onClose, setDirty, onSubmit };
}
describe('平台编辑弹窗', () => {
  it('空白表单点击取消直接关闭，免二次确认', async () => {
    const { onClose } = show();
    fireEvent.click(screen.getByRole('button', { name: '取 消' }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByText('有未保存的修改')).not.toBeInTheDocument();
  });
  it('空白表单点击弹窗外直接关闭', () => {
    const { onClose } = show();
    const outside = document.querySelector('.ant-modal-wrap')!;
    fireEvent.mouseDown(outside);
    fireEvent.click(outside);
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByText('有未保存的修改')).not.toBeInTheDocument();
  });
  it('有输入时在原弹窗提示，恢复初始值后直接关闭', async () => {
    const { onClose } = show({ name: '锦城物业' });
    const input = screen.getByRole('textbox', { name: '名称' });
    fireEvent.change(input, { target: { value: '新名称' } });
    fireEvent.click(screen.getByRole('button', { name: '取 消' }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText('有未保存的修改')).toBeInTheDocument();
    expect(document.querySelectorAll('.ant-modal')).toHaveLength(1);
    fireEvent.change(input, { target: { value: '锦城物业' } });
    fireEvent.click(screen.getByRole('button', { name: '取 消' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });
  it('提交期间阻止取消和重复提交', async () => {
    let finish!: () => void;
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const { onClose } = show({ name: '锦城物业' }, onSubmit);
    fireEvent.click(screen.getByRole('button', { name: /保 存/ }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
    expect(screen.getByRole('button', { name: '取 消' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /保 存/ }));
    expect(onSubmit).toHaveBeenCalledOnce();
    finish();
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });
});
