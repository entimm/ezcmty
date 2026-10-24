import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ImportsPage } from '../../src/shared/imports/ImportsPage';
import type { ImportsRuntime } from '../../src/shared/imports/runtime';
import { PaymentsPage } from '../../src/shared/payments/PaymentsPage';
import type { PaymentsRuntime } from '../../src/shared/payments/runtime';
afterEach(cleanup);
describe('物业业务上下文门禁', () => {
  it.each(['imports', 'import-new', 'import-detail'])(
    '未选择小区时%s不挂载业务查询',
    (page) => {
      const call = vi.fn();
      const runtime = {
        scope: 'property',
        communityId: '',
        api: { batches: call, batch: call, types: call },
        can: () => true,
        setDirty: vi.fn(),
      } as unknown as ImportsRuntime;
      render(
        <ImportsPage
          page={page}
          params={{ id: 'batch' }}
          go={vi.fn()}
          runtime={runtime}
        />,
      );
      expect(
        screen.getByText('请先在上方选择小区；若无可选小区，请联系管理员。'),
      ).toBeInTheDocument();
      expect(call).not.toHaveBeenCalled();
    },
  );
  it.each(['payments', 'payment-detail'])(
    '未选择小区时%s不退化为公司范围查询',
    (page) => {
      const call = vi.fn();
      const runtime = {
        scope: 'property',
        communityId: '',
        api: { orders: call, order: call, sharing: call, unfreezing: call },
        can: () => true,
        setDirty: vi.fn(),
      } as unknown as PaymentsRuntime;
      render(
        <PaymentsPage
          page={page}
          params={{ id: 'payment' }}
          go={vi.fn()}
          runtime={runtime}
        />,
      );
      expect(
        screen.getByText('请先在上方选择小区；若无可选小区，请联系管理员。'),
      ).toBeInTheDocument();
      expect(call).not.toHaveBeenCalled();
    },
  );
});
