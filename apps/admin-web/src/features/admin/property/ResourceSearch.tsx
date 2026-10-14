import { Button, Form, Input, Select, Space } from 'antd';
import { useId } from 'react';
import { CompanyPicker } from './CompanyPicker';

export function ResourceSearch({
  values,
  submit,
  reset,
  companyFilter,
  admin,
}: {
  values: {
    name?: string;
    code?: string;
    enabled?: boolean;
    property_company_id?: string;
    login_name?: string;
  };
  submit: (values: Record<string, string | undefined>) => void;
  reset: () => void;
  companyFilter?: boolean;
  admin?: boolean;
}) {
  const formId = useId();
  return (
    <Form
      name={`property-search-${formId}`}
      key={JSON.stringify(values)}
      layout="inline"
      style={{ marginBottom: 16, rowGap: 12 }}
      initialValues={{
        ...values,
        enabled:
          values.enabled === undefined ? undefined : String(values.enabled),
      }}
      onFinish={submit}
    >
      {admin ? (
        <Form.Item name="login_name" label="登录名">
          <Input allowClear maxLength={64} />
        </Form.Item>
      ) : (
        <>
          <Form.Item name="name" label="名称">
            <Input allowClear maxLength={160} />
          </Form.Item>
          <Form.Item name="code" label="编码">
            <Input allowClear maxLength={64} />
          </Form.Item>
        </>
      )}
      {companyFilter && (
        <Form.Item
          name="property_company_id"
          label="物业公司"
          style={{ minWidth: 280 }}
        >
          <CompanyPicker />
        </Form.Item>
      )}
      <Form.Item name="enabled" label="状态">
        <Select
          allowClear
          style={{ width: 120 }}
          options={[
            { value: 'true', label: '启用' },
            { value: 'false', label: '停用' },
          ]}
        />
      </Form.Item>
      <Space>
        <Button type="primary" htmlType="submit">
          查询
        </Button>
        <Button onClick={reset}>重置</Button>
      </Space>
    </Form>
  );
}
