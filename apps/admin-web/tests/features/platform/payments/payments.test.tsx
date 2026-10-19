import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { MerchantBinding } from '@/shared/payments/types';
import { renderRoutes } from '../../../app/platform-harness';
import {
  companyId,
  configuration,
  difference,
  identity,
  mockPayments,
  paymentId,
} from '../../../support/payments';
const inactiveBinding: MerchantBinding = {
  id: companyId,
  property_company_id: companyId,
  service_provider_merchant_no: '19000000',
  merchant_no: '19000001',
  merchant_name: '测试物业',
  enabled: false,
  max_ratio_bps: null,
  ratio_checked_at: null,
  row_version: 1,
  created_at: '2026-10-19T00:00:00Z',
  updated_at: '2026-10-19T00:00:00Z',
};
afterEach(() => vi.unstubAllGlobals());
it('does not offer configuration mutations to a configuration reader', async () => {
  mockPayments(identity('platform_admin', ['platform.payment_config.read']));
  renderRoutes(
    `/platform/property/companies/${companyId}/payment-configuration`,
  );
  expect(await screen.findByText('当前不可收款')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '创建停用商户绑定' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '发布完整新规则' }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it.each([false, true])(
  'prevents publishing rules without an active merchant (binding history: %s)',
  async (hasHistory) => {
    const fetcher = mockPayments(
      identity('platform_admin', [
        'platform.payment_config.read',
        'platform.payment_config.manage',
      ]),
      (path) => {
        if (path.endsWith('/merchant-bindings'))
          return Response.json({
            items: hasHistory ? [inactiveBinding] : [],
            total: hasHistory ? 1 : 0,
            page: 1,
            page_size: 20,
          });
      },
    );
    renderRoutes(
      `/platform/property/companies/${companyId}/payment-configuration`,
    );
    const publish = await screen.findByRole('button', {
      name: '发布完整新规则',
    });
    expect(publish).toBeDisabled();
    expect(
      screen.queryByLabelText('平台服务费比例（%）'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('请先激活收款商户')).toBeInTheDocument();
    if (hasHistory)
      expect(
        await screen.findByRole('button', { name: '核验并激活' }),
      ).toBeEnabled();
    fireEvent.click(publish);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith('/profit-sharing-rule-versions') &&
          init?.method === 'POST',
      ),
    ).toHaveLength(0);
  },
);
it('allows publishing the first rule after activating a merchant while payment readiness is false', async () => {
  let activated = false;
  const fetcher = mockPayments(
    identity('platform_admin', [
      'platform.payment_config.read',
      'platform.payment_config.manage',
    ]),
    (path, init) => {
      if (path.endsWith('/active-merchant-binding') && init?.method === 'PUT') {
        activated = true;
      }
      const binding = {
        ...inactiveBinding,
        enabled: activated,
        max_ratio_bps: activated ? 3000 : null,
        ratio_checked_at: activated ? inactiveBinding.created_at : null,
      };
      if (
        path.endsWith('/payment-configuration') ||
        (path.endsWith('/active-merchant-binding') && init?.method === 'PUT')
      )
        return Response.json({
          ...configuration,
          current_binding: activated ? binding : null,
          configuration_token: activated
            ? 'activated-token'
            : configuration.configuration_token,
        });
      if (path.endsWith('/merchant-bindings'))
        return Response.json({
          items: [binding],
          total: 1,
          page: 1,
          page_size: 20,
        });
      if (
        path.endsWith('/profit-sharing-rule-versions') &&
        init?.method === 'POST'
      )
        return Response.json({ id: paymentId }, { status: 201 });
    },
  );
  renderRoutes(
    `/platform/property/companies/${companyId}/payment-configuration`,
  );
  expect(
    await screen.findByRole('button', { name: '发布完整新规则' }),
  ).toBeDisabled();
  fireEvent.click(await screen.findByRole('button', { name: '核验并激活' }));
  const activationDialog = await screen.findByRole('dialog');
  fireEvent.click(
    within(activationDialog).getByRole('button', {
      name: '确 定',
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: '发布完整新规则' }),
    ).toBeEnabled(),
  );
  expect(screen.getByText('当前不可收款')).toBeInTheDocument();
  expect(screen.getByText('尚未发布')).toBeInTheDocument();
  expect(screen.queryByText('请先激活收款商户')).not.toBeInTheDocument();
  // jsdom 不运行 CSS 动画，在确认框开始关闭后补发过渡结束事件。
  await waitFor(() =>
    expect(activationDialog).toHaveClass('ant-zoom-leave-active'),
  );
  fireEvent.transitionEnd(activationDialog);
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole('button', { name: '发布完整新规则' }));
  const ruleDialog = await screen.findByRole('dialog');
  expect(within(ruleDialog).getByText('发布完整新规则')).toBeInTheDocument();
  fireEvent.click(
    within(ruleDialog).getByRole('button', { name: '发布新版本' }),
  );
  fireEvent.click(await screen.findByRole('button', { name: '确 定' }));
  expect(
    await screen.findByText('已发布新版本，仅影响后续新订单'),
  ).toBeInTheDocument();
  expect(ruleDialog).not.toBeInTheDocument();
  const write = fetcher.mock.calls.find(
    ([url, init]) =>
      String(url).endsWith('/profit-sharing-rule-versions') &&
      init?.method === 'POST',
  );
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({
    expected_configuration_token: 'activated-token',
    items: [{ rate_bps: 300 }],
  });
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
  fireEvent.click(
    await screen.findByRole('button', { name: '创建停用商户绑定' }),
  );
  const bindingDialog = await screen.findByRole('dialog');
  expect(
    within(bindingDialog).getByText('创建停用商户绑定'),
  ).toBeInTheDocument();
  fireEvent.change(
    within(bindingDialog).getByLabelText('已在线下取得并核实的特约商户号'),
    { target: { value: '19000001' } },
  );
  fireEvent.change(within(bindingDialog).getByLabelText('商户名称'), {
    target: { value: '测试物业' },
  });
  fireEvent.click(
    within(bindingDialog).getByRole('button', { name: '创建停用绑定' }),
  );
  const replay = await within(bindingDialog).findByRole('button', {
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
  expect(
    await screen.findByText('已创建停用绑定，请核验并激活后发布适用规则'),
  ).toBeInTheDocument();
  expect(bindingDialog).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '创建停用商户绑定' }));
  const reopenedDialog = await screen.findByRole('dialog');
  expect(
    within(reopenedDialog).getByLabelText('已在线下取得并核实的特约商户号'),
  ).toHaveValue('');
  expect(within(reopenedDialog).getByLabelText('商户名称')).toHaveValue('');
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
