import { Form, Input, type FormInstance } from 'antd';
import { ApiError } from './request-client';

export function passwordFields(
  form: FormInstance,
  field = 'password',
  label = '密码',
) {
  return (
    <>
      <Form.Item
        name={field}
        label={label}
        rules={[
          { required: true },
          { min: 12, max: 128, message: '密码长度为 12–128 字符' },
        ]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Form.Item
        name="confirm_password"
        label="确认密码"
        dependencies={[field]}
        rules={[
          { required: true },
          {
            validator: (_, value) =>
              value === form.getFieldValue(field)
                ? Promise.resolve()
                : Promise.reject(new Error('两次密码不一致')),
          },
        ]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
    </>
  );
}
export function applyFormErrors(
  form: FormInstance,
  error: unknown,
  fields: string[],
) {
  if (
    !(error instanceof ApiError) ||
    error.status !== 422 ||
    !Array.isArray(error.problem?.errors)
  )
    return;
  for (const issue of error.problem.errors) {
    if (issue && typeof issue === 'object' && Array.isArray(issue.location)) {
      const name = issue.location[issue.location[0] === 'body' ? 1 : 0];
      if (typeof name === 'string' && fields.includes(name))
        form.setFields([{ name, errors: ['请检查该字段的格式或长度'] }]);
    }
  }
}
