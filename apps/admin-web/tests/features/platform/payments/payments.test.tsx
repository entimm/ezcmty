import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { renderRoutes } from '../../../app/platform-harness';
import {
  companyId,
  difference,
  identity,
  mockPayments,
  paymentId,
} from '../../../support/payments';
afterEach(() => vi.unstubAllGlobals());
it('does not offer configuration mutations to a configuration reader', async () => {
  mockPayments(identity('platform_admin', ['platform.payment_config.read']));
  renderRoutes(
    `/platform/property/companies/${companyId}/payment-configuration`,
  );
  expect(await screen.findByText('当前不可收款')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '创建停用绑定' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '发布新版本' }),
  ).not.toBeInTheDocument();
});
it('replays an uncertain configuration creation with its original body and key', async () => {
  let attempts = 0;
  const fetcher = mockPayments(
    identity('platform_admin', [
      'platform.payment_config.read',
      'platform.payment_config.manage',
    ]),
    (path, init) => {
      if (path.endsWith('/merchant-bindings') && init?.method === 'POST') {
        attempts++;
        if (attempts === 1) throw new TypeError('network failure');
        return Response.json({ id: companyId }, { status: 201 });
      }
    },
  );
  renderRoutes(
    `/platform/property/companies/${companyId}/payment-configuration`,
  );
  fireEvent.change(
    await screen.findByLabelText('已在线下取得并核实的特约商户号'),
    { target: { value: '19000001' } },
  );
  fireEvent.change(screen.getByLabelText('商户名称'), {
    target: { value: '测试物业' },
  });
  fireEvent.click(screen.getByRole('button', { name: '创建停用绑定' }));
  const replay = await screen.findByRole('button', {
    name: '按原请求核实／重放',
  });
  await waitFor(() => expect(replay).toBeEnabled());
  fireEvent.click(replay);
  await waitFor(() => expect(attempts).toBe(2));
  const writes = fetcher.mock.calls.filter(
    ([url, init]) =>
      String(url).endsWith('/merchant-bindings') && init?.method === 'POST',
  );
  expect(writes[1][1]?.body).toBe(writes[0][1]?.body);
  expect(new Headers(writes[1][1]?.headers).get('Idempotency-Key')).toBe(
    new Headers(writes[0][1]?.headers).get('Idempotency-Key'),
  );
});
it('accepts recovery as a scheduled task without showing funds success', async () => {
  const fetcher = mockPayments(
    identity('platform_admin', [
      'platform.payment.read',
      'platform.payment_funds.recover',
    ]),
    (path) =>
      path.endsWith('/recoveries')
        ? Response.json(
            {
              target_type: 'payment_order',
              target_id: paymentId,
              accepted_at: '2026-10-19T00:00:00Z',
            },
            { status: 202 },
          )
        : undefined,
  );
  renderRoutes(`/platform/payments/${paymentId}`);
  fireEvent.click(
    await screen.findByRole('button', { name: '重新核实／恢复处理' }),
  );
  fireEvent.change(await screen.findByLabelText('恢复原因'), {
    target: { value: '核实原订单结果' },
  });
  fireEvent.click(screen.getByRole('button', { name: '安排恢复' }));
  expect(
    await screen.findByText('任务已安排，请查询实际结果'),
  ).toBeInTheDocument();
  const call = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith('/recoveries'),
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    reason: '核实原订单结果',
    expected_state_token: 'payment-token-1',
  });
});
it('records verified external resolution through its independent API and message', async () => {
  const fetcher = mockPayments(
    identity('platform_admin', [
      'platform.payment_reconciliation.read',
      'platform.payment_funds.recover',
    ]),
    (path) =>
      path.endsWith('/external-resolutions')
        ? Response.json({ ...difference, status: 'resolved' })
        : undefined,
  );
  renderRoutes(`/platform/payment-reconciliation?difference=${paymentId}`);
  fireEvent.click(await screen.findByRole('button', { name: '记录外部处置' }));
  fireEvent.change(await screen.findByLabelText('处置原因与结论'), {
    target: { value: '已核实渠道外部处理结论' },
  });
  fireEvent.change(screen.getByLabelText('已核实的外部工单／凭证引用'), {
    target: { value: '工单TEST-123' },
  });
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: '我已核实外部依据，确认该操作只记录差异处置',
    }),
  );
  fireEvent.click(
    screen.getAllByRole('button', { name: '记录外部处置' }).at(-1)!,
  );
  expect(await screen.findByText('已记录外部处置')).toBeInTheDocument();
  const call = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith('/external-resolutions'),
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    reason: '已核实渠道外部处理结论',
    evidence_reference: '工单TEST-123',
    expected_state_token: 'difference-token-1',
  });
  expect(screen.queryByText('资金已到账')).not.toBeInTheDocument();
});
it.each([409, 503])(
  'requires reading current evidence after external resolution HTTP %s without automatic resubmission',
  async (status) => {
    const fetcher = mockPayments(
      identity('platform_admin', [
        'platform.payment_reconciliation.read',
        'platform.payment_funds.recover',
      ]),
      (path) =>
        path.endsWith('/external-resolutions')
          ? Response.json(
              {
                type: 'about:blank',
                title: '需重新核实',
                status,
                detail: '请重新读取当前差异',
                instance: path,
                code: 'payment.state_changed',
                request_id: 'test',
              },
              { status },
            )
          : undefined,
    );
    renderRoutes(`/platform/payment-reconciliation?difference=${paymentId}`);
    fireEvent.click(
      await screen.findByRole('button', { name: '记录外部处置' }),
    );
    fireEvent.change(await screen.findByLabelText('处置原因与结论'), {
      target: { value: '已核实外部结论' },
    });
    fireEvent.change(screen.getByLabelText('已核实的外部工单／凭证引用'), {
      target: { value: '工单TEST-456' },
    });
    fireEvent.click(
      screen.getByRole('checkbox', {
        name: '我已核实外部依据，确认该操作只记录差异处置',
      }),
    );
    fireEvent.click(
      screen.getAllByRole('button', { name: '记录外部处置' }).at(-1)!,
    );
    expect(
      await screen.findByRole('button', { name: '核实详情与审计' }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole('button', { name: '记录外部处置' }).at(-1),
    ).toBeDisabled();
    await waitFor(() =>
      expect(
        fetcher.mock.calls.filter(([url]) =>
          String(url).endsWith(
            `/payment-reconciliation-discrepancies/${paymentId}`,
          ),
        ).length,
      ).toBeGreaterThan(1),
    );
    expect(
      fetcher.mock.calls.filter(([url]) =>
        String(url).endsWith('/external-resolutions'),
      ),
    ).toHaveLength(1);
    expect(screen.queryByText('已记录外部处置')).not.toBeInTheDocument();
  },
);
