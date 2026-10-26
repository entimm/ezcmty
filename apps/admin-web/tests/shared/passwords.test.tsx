import { createRef } from 'react';
import {
  act,
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { App, Button, Form, Input, type FormInstance } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import { existingPasswordRules } from '../../src/shared/forms';
import { PasswordFields } from '../../src/shared/system/components';

type PasswordMode = 'existing' | 'new';

function PasswordForm({
  mode,
  password,
  onFinish,
  formRef,
}: {
  mode: PasswordMode;
  password: string;
  onFinish: (values: object) => void;
  formRef: React.RefObject<FormInstance | null>;
}) {
  const [form] = Form.useForm();
  return (
    <Form
      form={form}
      ref={formRef}
      initialValues={{ password, confirm_password: password }}
      onFinish={onFinish}
    >
      {mode === 'existing' ? (
        <Form.Item name="password" label="密码" rules={existingPasswordRules}>
          <Input.Password />
        </Form.Item>
      ) : (
        <PasswordFields form={form} />
      )}
      <Button htmlType="submit">提交密码</Button>
    </Form>
  );
}

function show(mode: PasswordMode, password: string) {
  const submit = vi.fn();
  const form = createRef<FormInstance>();
  render(
    <App>
      <PasswordForm
        mode={mode}
        password={password}
        onFinish={submit}
        formRef={form}
      />
    </App>,
  );
  return { submit, form };
}

describe('已有密码长度与原文', () => {
  it.each([
    ['1 位', 'a'],
    ['11 位', 'a'.repeat(11)],
    ['12 位', 'a'.repeat(12)],
    ['128 位', 'a'.repeat(128)],
    ['128 个 emoji', '😀'.repeat(128)],
    ['单个空格', ' '],
    ['首尾空格', ' a '],
  ])('接受%s并原样提交', async (_name, password) => {
    const { submit } = show('existing', password);
    fireEvent.click(screen.getByRole('button', { name: '提交密码' }));
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith(
        expect.objectContaining({ password }),
      ),
    );
  });

  it.each([
    ['空串', '', '请输入密码'],
    ['129 位', 'a'.repeat(129), '密码长度为1–128位'],
    ['129 个 emoji', '😀'.repeat(129), '密码长度为1–128位'],
  ])('拒绝%s且不截断输入', async (_name, password, error) => {
    const { submit, form } = show('existing', password);
    fireEvent.click(screen.getByRole('button', { name: '提交密码' }));
    await screen.findByText(error);
    expect(submit).not.toHaveBeenCalled();
    expect(form.current?.getFieldValue('password')).toBe(password);
    expect(screen.getByLabelText('密码')).toHaveValue(password);
  });
});

describe('创建与重置临时密码', () => {
  it.each([
    ['12 位纯字母', 'a'.repeat(12)],
    ['128 位纯字母', 'a'.repeat(128)],
    ['128 个 emoji', '😀'.repeat(128)],
    ['中文', '密码'.repeat(6)],
    ['12 个空格', ' '.repeat(12)],
    ['首尾空格', ` ${'a'.repeat(12)} `],
  ])('接受%s并原样提交', async (_name, password) => {
    const { submit } = show('new', password);
    fireEvent.click(screen.getByRole('button', { name: '提交密码' }));
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith({
        password,
        confirm_password: password,
      }),
    );
  });

  it.each([
    ['空串', '', '请输入密码'],
    ['11 位', 'a'.repeat(11), '密码长度为12–128位'],
    ['129 位', 'a'.repeat(129), '密码长度为12–128位'],
    ['129 个 emoji', '😀'.repeat(129), '密码长度为12–128位'],
    ['中间 CR', `aaaaaa\raaaaaa`, '密码不能包含换行符'],
    ['末尾 LF', `${'a'.repeat(12)}\n`, '密码不能包含换行符'],
    ['CRLF', `aaaaaa\r\naaaaaa`, '密码不能包含换行符'],
  ])('拒绝%s且保留表单原文', async (_name, password, error) => {
    const { submit, form } = show('new', password);
    fireEvent.click(screen.getByRole('button', { name: '提交密码' }));
    await screen.findByText(error);
    expect(submit).not.toHaveBeenCalled();
    expect(form.current?.getFieldValue('password')).toBe(password);
  });

  it('确认密码比较原文，首尾空格不被忽略', async () => {
    const password = 'a'.repeat(12);
    const { submit } = show('new', password);
    fireEvent.change(screen.getByLabelText('确认临时密码'), {
      target: { value: ` ${password}` },
    });
    fireEvent.click(screen.getByRole('button', { name: '提交密码' }));
    await screen.findByText('两次密码不一致');
    expect(submit).not.toHaveBeenCalled();
  });

  it.each([
    ['临时密码', '\r'],
    ['临时密码', '\n'],
    ['确认临时密码', '\r\n'],
  ])('%s拒绝带换行的粘贴，原输入保持不变', async (label, lineBreak) => {
    const password = 'a'.repeat(12);
    const { submit } = show('new', password);
    const input = screen.getByLabelText(label);
    const paste = createEvent.paste(input, {
      clipboardData: { getData: () => `${password}${lineBreak}` },
    });
    fireEvent(input, paste);
    expect(paste.defaultPrevented).toBe(true);
    await screen.findByText('密码不能包含换行符，请粘贴不含换行的内容');
    expect(input).toHaveValue(password);
    expect(submit).not.toHaveBeenCalled();
  });

  it('允许粘贴不含换行的原文', () => {
    show('new', '');
    const input = screen.getByLabelText('临时密码');
    const paste = createEvent.paste(input, {
      clipboardData: { getData: () => ` ${'😀'.repeat(12)} ` },
    });
    fireEvent(input, paste);
    expect(paste.defaultPrevented).toBe(false);
  });

  it('程序设置含换行的密码也不能通过表单校验', async () => {
    const { form, submit } = show('new', 'a'.repeat(12));
    const password = `${'a'.repeat(12)}\n`;
    act(() =>
      form.current?.setFieldsValue({ password, confirm_password: password }),
    );
    fireEvent.click(screen.getByRole('button', { name: '提交密码' }));
    await screen.findByText('密码不能包含换行符');
    expect(submit).not.toHaveBeenCalled();
  });
});
