import { useQuery } from '@tanstack/react-query';
import {
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tabs,
  Typography,
} from 'antd';
import { ReadError } from '../../components/AdminFeedback';
import { useListState } from '../hooks/use-list-state';
import { useImports } from './runtime';
import { actionNames, cell, resultNames } from './values';
import type { Batch, Filters, ImportRow, Issue } from './types';
export function RowsPanel({ batch }: { batch: Batch }) {
  const { api, can } = useImports(),
    rowsState = useListState('rows_'),
    issueState = useListState('issues_');
  const rowsFilters: Filters = {
    page: rowsState.page,
    page_size: rowsState.pageSize,
  };
  for (const key of [
    'precheck_status',
    'execution_status',
    'planned_action',
    'field_key',
  ])
    rowsFilters[key] = rowsState.params.get(key) || undefined;
  const rowNo = Number(rowsState.params.get('row_no'));
  if (Number.isInteger(rowNo) && rowNo > 0) rowsFilters.row_no = rowNo;
  const issuesFilters: Filters = {
    page: issueState.page,
    page_size: issueState.pageSize,
  };
  for (const key of ['severity', 'code', 'field_key', 'phase'])
    issuesFilters[key] = issueState.params.get(key) || undefined;
  const located = Number(issueState.params.get('row_no'));
  if (Number.isInteger(located) && located > 0) issuesFilters.row_no = located;
  const rows = useQuery({
    queryKey: [
      'imports',
      batch.id,
      'rows',
      batch.preview?.version,
      batch.updated_at,
      rowsFilters,
    ],
    queryFn: ({ signal }) => api.rows(batch.id, rowsFilters, signal),
    enabled: !!batch.preview && can('read'),
  });
  const issues = useQuery({
    queryKey: [
      'imports',
      batch.id,
      'issues',
      batch.preview?.version,
      batch.updated_at,
      issuesFilters,
    ],
    queryFn: ({ signal }) => api.issues(batch.id, issuesFilters, signal),
    enabled: can('read'),
  });
  const template = useQuery({
    queryKey: [
      'imports',
      'template',
      batch.template.key,
      batch.template.version_no,
    ],
    queryFn: ({ signal }) =>
      api.template(batch.template.key, batch.template.version_no, signal),
    enabled: can('create') && !!batch.preview,
  });
  const locatedRows = useQuery({
    queryKey: [
      'imports',
      batch.id,
      'located-row',
      batch.preview?.version,
      batch.updated_at,
      located,
    ],
    queryFn: ({ signal }) =>
      api.rows(batch.id, { page: 1, page_size: 1, row_no: located }, signal),
    enabled: located > 0 && !!batch.preview && can('read'),
  });
  const selected =
    locatedRows.data?.items[0] ||
    rows.data?.items.find((row) => row.row_no === located);

  const keys =
    template.data?.fields.map((field) => ({
      key: field.key,
      label: field.label,
    })) ||
    Object.keys(rows.data?.items[0]?.raw_values || {}).map((key) => ({
      key,
      label: key,
    }));
  const issueColumns = [
    { title: '原始行号', dataIndex: 'row_no', render: cell },
    {
      title: '位置',
      render: (_: unknown, row: Issue) =>
        row.cell_reference ||
        [row.column_name, row.column_index].filter(Boolean).join(' / ') ||
        '文件级问题',
    },
    { title: '字段', dataIndex: 'field_key', render: cell },
    {
      title: '级别',
      dataIndex: 'severity',
      render: (value: string) => (value === 'error' ? '错误' : '警告'),
    },
    { title: '错误码', dataIndex: 'code' },
    { title: '说明', dataIndex: 'message' },
    { title: '修复建议', dataIndex: 'suggestion', render: cell },
    { title: '原始值', dataIndex: 'raw_value', render: cell },
    { title: '规范化值', dataIndex: 'normalized_value', render: cell },
    {
      title: '可重试',
      dataIndex: 'retryable',
      render: (value: boolean) => (value ? '是' : '否'),
    },
  ];
  return (
    <>
      <Tabs
        items={[
          {
            key: 'rows',
            label: '行预览与结果',
            children: (
              <Space orientation="vertical" style={{ width: '100%' }}>
                <Form
                  layout="inline"
                  initialValues={Object.fromEntries(rowsState.params)}
                  onFinish={(value: Record<string, string>) =>
                    rowsState.update({ ...value, page: 1 })
                  }
                >
                  <Form.Item label="校验结果" name="precheck_status">
                    <Select
                      allowClear
                      style={{ width: 120 }}
                      options={[
                        { value: 'valid', label: '通过' },
                        { value: 'warning', label: '警告' },
                        { value: 'error', label: '错误' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label="计划动作" name="planned_action">
                    <Select
                      allowClear
                      style={{ width: 120 }}
                      options={Object.entries(actionNames).map(
                        ([value, label]) => ({ value, label }),
                      )}
                    />
                  </Form.Item>
                  <Form.Item label="执行结果" name="execution_status">
                    <Select
                      allowClear
                      style={{ width: 130 }}
                      options={Object.entries(resultNames).map(
                        ([value, label]) => ({ value, label }),
                      )}
                    />
                  </Form.Item>
                  <Form.Item label="原始行号" name="row_no">
                    <Input type="number" min={1} style={{ width: 110 }} />
                  </Form.Item>
                  <Form.Item label="字段编码" name="field_key">
                    <Input />
                  </Form.Item>
                  <Button htmlType="submit">筛选行</Button>
                </Form>
                {rows.isError ? (
                  <ReadError
                    error={rows.error}
                    retry={() => void rows.refetch()}
                  />
                ) : (
                  <Table<ImportRow>
                    rowKey="id"
                    loading={rows.isLoading}
                    dataSource={rows.data?.items}
                    pagination={{
                      ...rowsState.pagination,
                      total: rows.data?.total,
                    }}
                    scroll={{ x: 1000 }}
                    locale={{
                      emptyText: batch.preview ? '没有匹配行' : '尚未发布预览',
                    }}
                    columns={[
                      {
                        title: '原始行号',
                        dataIndex: 'row_no',
                        render: (value: number) => (
                          <Button
                            type="link"
                            onClick={() =>
                              issueState.update({ row_no: value, page: 1 })
                            }
                          >
                            {value}
                          </Button>
                        ),
                      },
                      ...keys.map((field) => ({
                        title: field.label,
                        key: field.key,
                        render: (_: unknown, row: ImportRow) => (
                          <>
                            <div>原始：{cell(row.raw_values[field.key])}</div>
                            <div>
                              规范化：{cell(row.normalized_values?.[field.key])}
                            </div>
                          </>
                        ),
                      })),
                      {
                        title: '计划动作',
                        dataIndex: 'planned_action',
                        render: (v: string) => actionNames[v],
                      },
                      { title: '校验结果', dataIndex: 'precheck_status' },
                      { title: '问题数', dataIndex: 'issue_count' },
                      {
                        title: '实际结果',
                        dataIndex: 'execution_status',
                        render: (v: string) => resultNames[v],
                      },
                      {
                        title: '结果说明',
                        dataIndex: 'result_message',
                        render: cell,
                      },
                    ]}
                  />
                )}
              </Space>
            ),
          },
          {
            key: 'issues',
            label: '问题定位',
            children: (
              <Space orientation="vertical" style={{ width: '100%' }}>
                <Form
                  layout="inline"
                  initialValues={Object.fromEntries(issueState.params)}
                  onFinish={(value: Record<string, string>) =>
                    issueState.update({ ...value, page: 1 })
                  }
                >
                  <Form.Item label="问题级别" name="severity">
                    <Select
                      allowClear
                      style={{ width: 120 }}
                      options={[
                        { value: 'error', label: '错误' },
                        { value: 'warning', label: '警告' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label="错误码" name="code">
                    <Input />
                  </Form.Item>
                  <Form.Item label="字段编码" name="field_key">
                    <Input />
                  </Form.Item>
                  <Form.Item label="原始行号" name="row_no">
                    <Input type="number" min={1} />
                  </Form.Item>
                  <Button htmlType="submit">筛选问题</Button>
                </Form>
                {issues.isError ? (
                  <ReadError
                    error={issues.error}
                    retry={() => void issues.refetch()}
                  />
                ) : (
                  <Table<Issue>
                    rowKey="id"
                    dataSource={issues.data?.items}
                    loading={issues.isLoading}
                    pagination={{
                      ...issueState.pagination,
                      total: issues.data?.total,
                    }}
                    columns={issueColumns}
                    scroll={{ x: 1400 }}
                  />
                )}
              </Space>
            ),
          },
        ]}
      />
      <Drawer
        open={located > 0}
        title={`原始行 ${located} 的问题`}
        onClose={() => issueState.update({ row_no: undefined })}
        size="large"
      >
        {selected && (
          <>
            <Descriptions
              title="原始值与规范化值"
              column={1}
              items={Object.entries(selected.raw_values).map(
                ([key, value]) => ({
                  key,
                  label: key,
                  children: `${cell(value)} → ${cell(selected.normalized_values?.[key])}`,
                }),
              )}
            />
            <Typography.Paragraph>
              计划动作：{actionNames[selected.planned_action]}；实际结果：
              {resultNames[selected.execution_status]}
            </Typography.Paragraph>
          </>
        )}
        {issues.isError ? (
          <ReadError error={issues.error} retry={() => void issues.refetch()} />
        ) : (
          <Table<Issue>
            rowKey="id"
            size="small"
            dataSource={issues.data?.items}
            columns={issueColumns}
            scroll={{ x: 1200 }}
            pagination={{ ...issueState.pagination, total: issues.data?.total }}
          />
        )}
      </Drawer>
    </>
  );
}
