import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { renderRoutes } from '../../app/platform-harness';
import {
  batch,
  batchId,
  errorFile,
  hash,
  mockImports,
} from '../../support/imports';
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});
it.each(['platform', 'property'] as const)(
  'shows the empty production catalogue and disables creation on %s',
  async (owner) => {
    mockImports(
      `${owner}_admin`,
      [`${owner}.import.read`, `${owner}.import.create`],
      (path) =>
        path.endsWith('/import-types')
          ? Response.json({ items: [] })
          : undefined,
    );
    renderRoutes(`/${owner}/imports`);
    expect(await screen.findByText('尚无可用导入类型')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新建导入' })).toHaveAttribute(
      'disabled',
    );
  },
);
it('requires explicit valid-row policy and an explicit warning choice before confirming the fixed preview', async () => {
  const fetcher = mockImports(
    'platform_admin',
    ['platform.import.read', 'platform.import.execute'],
    (path, init) =>
      path.endsWith('/confirm') && init?.method === 'POST'
        ? Response.json(
            {
              batch_id: batchId,
              status: 'executing',
              phase: 'apply_queued',
              preview_version: 1,
              active_task: null,
              source_artifact: null,
            },
            { status: 202 },
          )
        : undefined,
  );
  renderRoutes(`/platform/imports/${batchId}`);
  fireEvent.click(await screen.findByRole('button', { name: '确认执行' }));
  const dialog = await screen.findByRole('dialog');
  const confirm = within(dialog).getByRole('button', {
    name: '确认并安排执行',
  });
  expect(confirm).toBeDisabled();
  fireEvent.click(
    within(dialog).getByRole('radio', { name: '仅执行通过行，排除普通错误行' }),
  );
  fireEvent.click(
    within(dialog).getByRole('checkbox', {
      name: '我已确认锁定范围、模板版本与执行策略',
    }),
  );
  expect(confirm).toBeDisabled();
  fireEvent.click(within(dialog).getByRole('radio', { name: '排除警告行' }));
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith('/confirm') && init?.method === 'POST',
      ),
    ).toBe(true),
  );
  const call = fetcher.mock.calls.find(
    ([url, init]) =>
      String(url).endsWith('/confirm') && init?.method === 'POST',
  )!;
  expect(JSON.parse(String(call[1]?.body))).toEqual({
    preview_version: 1,
    preview_fingerprint: hash,
    apply_policy: 'valid_rows_only',
    include_warning_rows: false,
  });
  expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toBeTruthy();
  expect(new Headers(call[1]?.headers).get('X-CSRF-Token')).toBe('csrf-token');
});
it('keeps the original key and original input after an unknown confirm result', async () => {
  let attempts = 0;
  const fetcher = mockImports(
    'platform_admin',
    ['platform.import.read', 'platform.import.execute'],
    (path, init) => {
      if (path.endsWith('/confirm') && init?.method === 'POST') {
        attempts++;
        if (attempts === 1) throw new TypeError('offline');
        return Response.json(
          {
            batch_id: batchId,
            status: 'executing',
            phase: 'apply_queued',
            preview_version: 1,
            active_task: null,
            source_artifact: null,
          },
          { status: 202 },
        );
      }
    },
  );
  renderRoutes(`/platform/imports/${batchId}`);
  fireEvent.click(await screen.findByRole('button', { name: '确认执行' }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(
    within(dialog).getByRole('radio', { name: '仅执行通过行，排除普通错误行' }),
  );
  fireEvent.click(within(dialog).getByRole('radio', { name: '执行警告行' }));
  fireEvent.click(within(dialog).getByRole('checkbox'));
  fireEvent.click(
    within(dialog).getByRole('button', { name: '确认并安排执行' }),
  );
  const replay = await screen.findByRole('button', {
    name: '使用原请求核实结果',
  });
  fireEvent.click(replay);
  await waitFor(() => expect(attempts).toBe(2));
  const calls = fetcher.mock.calls.filter(
    ([url, init]) =>
      String(url).endsWith('/confirm') && init?.method === 'POST',
  );
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body);
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(
    new Headers(calls[1][1]?.headers).get('Idempotency-Key'),
  );
});
it('hides writes from readers and does not expose stale error files for download', async () => {
  const fetcher = mockImports(
    'property_admin',
    ['property.import.read', 'property.import.download'],
    (path) =>
      path.endsWith('/artifacts/error-file')
        ? Response.json({
            ...errorFile,
            status: 'stale',
            generation: 1,
            downloadable: false,
          })
        : undefined,
  );
  renderRoutes(`/property/imports/${batchId}`);
  expect(await screen.findByText('已失效，需重新生成')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '确认执行' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '下载当前代次错误文件' }),
  ).not.toBeInTheDocument();
  expect(
    fetcher.mock.calls.every(
      ([url]) => !String(url).includes('/api/platform/'),
    ),
  ).toBe(true);
});
it('keeps uncertain results separate and offers original-task recovery instead of retry', async () => {
  mockImports(
    'platform_admin',
    [
      'platform.import.read',
      'platform.import.recover',
      'platform.import.retry',
    ],
    (path) =>
      path.endsWith(`/import-batches/${batchId}`)
        ? Response.json({
            ...batch,
            status: 'blocked',
            phase: 'recovery',
            blocked_reason: '需要核实原操作',
            last_error_code: 'import.result_uncertain',
            statistics: {
              ...batch.statistics,
              execution: { ...batch.statistics.execution, uncertain_rows: 1 },
            },
            next_actions: ['recover'],
          })
        : undefined,
  );
  renderRoutes(`/platform/imports/${batchId}`);
  expect(
    await screen.findByText('存在待核实结果，请核实并恢复原任务'),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: '核实并恢复原任务' }),
  ).toBeEnabled();
  expect(
    screen.queryByRole('button', { name: '失败行重跑' }),
  ).not.toBeInTheDocument();
});
it('restores row location from the URL without writing raw values to it', async () => {
  const fetcher = mockImports(
    'platform_admin',
    ['platform.import.read'],
    (path) =>
      path.endsWith('/issues')
        ? Response.json({
            items: [
              {
                id: batchId,
                preview_version: 1,
                phase: 'precheck',
                row_no: 7,
                column_index: 1,
                column_name: '名称',
                field_key: 'title',
                cell_reference: 'A7',
                severity: 'error',
                code: 'import.required',
                message: '名称不能为空',
                suggestion: '补全名称',
                raw_value: '掩码',
                normalized_value: null,
                retryable: false,
              },
            ],
            total: 1,
            page: 1,
            page_size: 20,
          })
        : undefined,
  );
  renderRoutes(`/platform/imports/${batchId}?issues_row_no=7`);
  const drawer = await screen.findByRole('dialog');
  expect(within(drawer).getByText('原始行 7 的问题')).toBeInTheDocument();
  expect(await within(drawer).findByText('A7')).toBeInTheDocument();
  expect(screen.getByTestId('location')).toHaveTextContent('issues_row_no=7');
  expect(
    fetcher.mock.calls.some(
      ([url]) =>
        String(url).includes('/issues?') && String(url).includes('row_no=7'),
    ),
  ).toBe(true);
});
it('disables expired preview confirmation and retains manual precheck', async () => {
  mockImports(
    'platform_admin',
    [
      'platform.import.read',
      'platform.import.execute',
      'platform.import.precheck',
    ],
    (path) =>
      path.endsWith(`/import-batches/${batchId}`)
        ? Response.json({
            ...batch,
            preview: { ...batch.preview!, expires_at: '2000-01-01T00:00:00Z' },
          })
        : undefined,
  );
  renderRoutes(`/platform/imports/${batchId}`);
  expect(
    await screen.findByRole('button', { name: '确认执行' }),
  ).toBeDisabled();
  expect(screen.getByRole('button', { name: '重新预检' })).toBeEnabled();
});

it.each(['platform', 'property'] as const)(
  'creates a nonempty-catalogue draft with %s company ownership',
  async (owner) => {
    const fetcher = mockImports(
      `${owner}_admin`,
      [`${owner}.import.read`, `${owner}.import.create`],
      (path, init) =>
        path.endsWith('/import-batches') && init?.method === 'POST'
          ? Response.json(
              {
                batch_id: batchId,
                status: 'draft',
                phase: 'awaiting_source_file',
                preview_version: 0,
                active_task: null,
                source_artifact: null,
              },
              { status: 201 },
            )
          : undefined,
    );
    renderRoutes(`/${owner}/imports/new`);
    const typeSelector = await screen.findByRole('combobox', {
      name: '导入类型',
    });
    fireEvent.mouseDown(typeSelector);
    fireEvent.click(
      await screen.findByText('测试记录导入', {
        selector: '.ant-select-item-option-content',
      }),
    );
    if (owner === 'platform') {
      const company = await screen.findByRole('combobox', { name: '目标公司' });
      fireEvent.mouseDown(company);
      fireEvent.click(
        await screen.findByText('测试物业公司', {
          selector: '.ant-select-item-option-content',
        }),
      );
    }
    const create = await screen.findByRole('button', {
      name: '创建草稿，下一步上传文件',
    });
    await waitFor(() => expect(create).toBeEnabled());
    expect(
      await screen.findByText('范围已锁定：测试物业公司'),
    ).toBeInTheDocument();
    expect(await screen.findByText('去除首尾空格')).toBeInTheDocument();
    fireEvent.click(create);
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/import-batches') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/import-batches') && init?.method === 'POST',
    )!;
    const body = JSON.parse(String(call[1]?.body));
    expect(body.scope).toEqual({
      type: 'company',
      id: batch.property_company_id,
    });
    expect(body.mode).toBe('create');
    expect(body.template_version_no).toBe(1);
    if (owner === 'platform')
      expect(body.property_company_id).toBe(batch.property_company_id);
    else expect(body).not.toHaveProperty('property_company_id');
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(
        `/${owner}/imports/${batchId}`,
      ),
    );
  },
);
