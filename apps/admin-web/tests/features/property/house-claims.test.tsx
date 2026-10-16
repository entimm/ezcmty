import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderRoutes } from '../../app/platform-harness';
import type { SessionResponse } from '@/shared/api/admin';
import type { Claim, HouseBinding } from '@/features/property/house-claims/api';

const community = '019a0000-0000-7000-8000-000000000001';
const house = '019a0000-0000-7000-8000-000000000002';
const claimId = '019a0000-0000-7000-8000-000000000003';
const bindingId = '019a0000-0000-7000-8000-000000000004';
const timestamp = '2026-10-17T01:00:00Z';
const root = '/api/property/v1';
const claimPath = `/house-claims/${claimId}`;
const bindingPath = `/resident-house-bindings/${bindingId}`;
const permissions = [
  'property.house_claim.read',
  'property.house_claim.review',
  'property.resident_house_binding.read',
  'property.resident_house_binding.revoke',
];
const identity: SessionResponse = {
  scope: 'property_admin',
  subject_id: community,
  login_name: 'reviewer',
  display_name: '审核员',
  permissions,
  must_change_password: false,
  csrf_token: 'claim-csrf',
};
const claim: Claim = {
  id: claimId,
  property_company_id: community,
  community_id: community,
  house_id: house,
  user_id: community,
  house_label_snapshot: '春日小区／一号楼／101',
  applicant_name: '李女士',
  applicant_phone: '13812345678',
  applicant_remark: '请物业核实',
  status: 'pending',
  match_status: 'unmatched',
  matched_owner_id: null,
  review_reason: null,
  reviewed_by_admin_id: null,
  reviewed_at: null,
  cancelled_at: null,
  row_version: 3,
  created_at: timestamp,
  updated_at: timestamp,
};
const binding: HouseBinding = {
  id: bindingId,
  property_company_id: community,
  community_id: community,
  house_id: house,
  user_id: community,
  claim_application_id: claimId,
  house_label_snapshot: claim.house_label_snapshot,
  applicant_name: claim.applicant_name,
  applicant_phone: claim.applicant_phone,
  status: 'active',
  effective_enabled: true,
  granted_at: timestamp,
  ended_at: null,
  end_reason: null,
  row_version: 5,
  created_at: timestamp,
  updated_at: timestamp,
};
function mockClaims(
  options: {
    permissions?: string[];
    matched?: boolean;
    outcome?: 'conflict' | 'unknown';
    terminal?: boolean;
  } = {},
) {
  let currentClaim = {
    ...claim,
    match_status: options.matched ? 'matched' : 'unmatched',
    status: options.terminal ? 'approved' : 'pending',
  } as Claim;
  let currentBinding = { ...binding };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const target = new URL(String(url), window.location.origin);
    const path = target.pathname.replace(root, '');
    const page = (items: unknown[], total = items.length) =>
      Response.json({
        items,
        total,
        page: Number(target.searchParams.get('page') || 1),
        page_size: Number(target.searchParams.get('page_size') || 20),
      });
    if (path === '/admin-sessions/current')
      return Response.json({
        ...identity,
        permissions: options.permissions ?? permissions,
      });
    if (path === `${claimPath}/reviews`) {
      const data = JSON.parse(String(init?.body)) as {
        decision: 'approved' | 'rejected';
        reason?: string;
      };
      currentClaim = {
        ...currentClaim,
        status: options.outcome === 'conflict' ? 'cancelled' : data.decision,
        row_version: 4,
        review_reason: data.reason ?? null,
        reviewed_at: timestamp,
      };
      if (options.outcome)
        return Response.json(
          {
            type: 'about:blank',
            title: '状态已变化',
            status: options.outcome === 'conflict' ? 409 : 503,
            detail:
              options.outcome === 'conflict'
                ? '申请状态已变化'
                : '服务暂不可用',
            code: 'house_claim.state_changed',
            instance: path,
            request_id: 'claim-request',
          },
          {
            status: options.outcome === 'conflict' ? 409 : 503,
            headers: { 'Content-Type': 'application/problem+json' },
          },
        );
      return Response.json(currentClaim);
    }
    if (path === claimPath) return Response.json(currentClaim);
    if (path === '/house-claims') return page([currentClaim]);
    if (path === `${bindingPath}/revocations`) {
      const data = JSON.parse(String(init?.body)) as { reason: string };
      currentBinding = {
        ...currentBinding,
        status: 'revoked',
        effective_enabled: false,
        end_reason: data.reason,
        ended_at: timestamp,
        row_version: 6,
      };
      return Response.json(currentBinding);
    }
    if (path === bindingPath) return Response.json(currentBinding);
    if (path === '/resident-house-bindings') return page([currentBinding]);
    if (path.endsWith('/owners'))
      return page(
        [
          {
            id: 'owner',
            house_id: house,
            name: '档案业主',
            phone: '13912345678',
            enabled: true,
            effective_enabled: true,
            created_at: timestamp,
            updated_at: timestamp,
          },
        ],
        101,
      );
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
const writes = (fetcher: ReturnType<typeof mockClaims>) =>
  fetcher.mock.calls.filter(([, init]) => init?.method === 'POST');
afterEach(() => vi.unstubAllGlobals());

describe('property house claims', () => {
  it('defaults to pending claims and masks list phones without exposing owner archives', async () => {
    const fetcher = mockClaims();
    renderRoutes('/property/house-claims');
    expect(await screen.findByText('138****5678')).toBeInTheDocument();
    expect(screen.queryByText(claim.applicant_phone)).not.toBeInTheDocument();
    const request = fetcher.mock.calls.find(
      ([url]) => new URL(String(url)).pathname === `${root}/house-claims`,
    )!;
    expect(
      Object.fromEntries(new URL(String(request[0])).searchParams),
    ).toEqual({
      status: 'pending',
      page: '1',
      page_size: '20',
      sort: '-created_at',
    });
    expect(request[1]?.cache).toBe('no-store');
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes('/owners')),
    ).toBe(false);
  });

  it('restores company-scoped filters, time, page and stable sorting from the URL', async () => {
    const fetcher = mockClaims();
    renderRoutes(
      `/property/house-claims?status=all&community_id=${community}&house_id=${house}&match_status=unmatched&created_from=2026-10-16T00%3A00%3A00Z&page=2&sort=created_at`,
    );
    await screen.findByText('138****5678');
    const request = fetcher.mock.calls.find(
      ([url]) => new URL(String(url)).pathname === `${root}/house-claims`,
    )!;
    expect(
      Object.fromEntries(new URL(String(request[0])).searchParams),
    ).toMatchObject({
      community_id: community,
      house_id: house,
      match_status: 'unmatched',
      created_from: '2026-10-16T00:00:00Z',
      page: '2',
      sort: 'created_at',
    });
    expect(new URL(String(request[0])).searchParams.has('status')).toBe(false);
    expect(
      fetcher.mock.calls.every(([url]) =>
        new URL(String(url)).pathname.startsWith(root),
      ),
    ).toBe(true);
    expect(screen.getByTestId('location').textContent).not.toContain(
      claim.applicant_phone,
    );
  });

  it('blocks forbidden routes before reading business data', async () => {
    const fetcher = mockClaims({ permissions: [] });
    renderRoutes(`/property${claimPath}`);
    expect(await screen.findByText('无权访问此页面')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes('/house-claims')),
    ).toBe(false);
  });

  it('keeps applicant and owner read permissions separate and hides review actions for readers', async () => {
    const fetcher = mockClaims({ permissions: ['property.house_claim.read'] });
    renderRoutes(`/property${claimPath}`);
    expect(await screen.findByText(claim.applicant_phone)).toBeInTheDocument();
    expect(screen.getByText('没有业主资料读取权限。')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '通过申请' }),
    ).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes('/owners')),
    ).toBe(false);
  });

  it('loads paginated owner archives only with their own read permission', async () => {
    const fetcher = mockClaims({
      permissions: ['property.house_claim.read', 'property.house_owner.read'],
    });
    renderRoutes(`/property${claimPath}`);
    expect(await screen.findByText('档案业主')).toBeInTheDocument();
    expect(screen.getByText('13912345678')).toBeInTheDocument();
    const request = fetcher.mock.calls.find(([url]) =>
      String(url).includes('/owners'),
    )!;
    expect(new URL(String(request[0])).pathname).toBe(
      `${root}/communities/${community}/houses/${house}/owners`,
    );
    expect(request[1]?.cache).toBe('no-store');
  });

  it.each([
    { decision: 'approved', open: '通过申请', confirm: '确认通过' },
    { decision: 'rejected', open: '驳回申请', confirm: '确认驳回' },
  ])(
    'requires a reason for unmatched $decision and submits the displayed version',
    async ({ decision, open, confirm }) => {
      const fetcher = mockClaims();
      renderRoutes(`/property${claimPath}`);
      await screen.findByText(claim.applicant_phone);
      fireEvent.click(screen.getByRole('button', { name: open }));
      const editor = within(await screen.findByRole('dialog'));
      fireEvent.click(editor.getByRole('button', { name: confirm }));
      expect(await editor.findByText('请填写原因')).toBeInTheDocument();
      expect(writes(fetcher)).toHaveLength(0);
      fireEvent.change(editor.getByLabelText('审核说明'), {
        target: { value: '  已核对纸质产权材料  ' },
      });
      fireEvent.click(editor.getByRole('button', { name: confirm }));
      await waitFor(() =>
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
      );
      const write = writes(fetcher)[0];
      expect(JSON.parse(String(write[1]?.body))).toEqual({
        expected_row_version: 3,
        decision,
        reason: '已核对纸质产权材料',
      });
      expect(new Headers(write[1]?.headers).get('X-CSRF-Token')).toBe(
        'claim-csrf',
      );
      expect(
        fetcher.mock.calls.some(
          ([url, init]) => /owners/.test(String(url)) && !!init?.method,
        ),
      ).toBe(false);
    },
  );

  it('allows a matched approval without a reason but still requires explicit review', async () => {
    const fetcher = mockClaims({ matched: true });
    renderRoutes(`/property${claimPath}`);
    await screen.findByText(claim.applicant_phone);
    expect(writes(fetcher)).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: '通过申请' }));
    fireEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: '确认通过',
      }),
    );
    await waitFor(() => expect(writes(fetcher)).toHaveLength(1));
    expect(JSON.parse(String(writes(fetcher)[0][1]?.body))).toEqual({
      expected_row_version: 3,
      decision: 'approved',
    });
  });

  it.each(['conflict', 'unknown'] as const)(
    'verifies %s outcomes without automatically resending the review',
    async (outcome) => {
      const fetcher = mockClaims({ matched: true, outcome });
      renderRoutes(`/property${claimPath}`);
      await screen.findByText(claim.applicant_phone);
      fireEvent.click(screen.getByRole('button', { name: '通过申请' }));
      const editor = within(await screen.findByRole('dialog'));
      fireEvent.click(editor.getByRole('button', { name: '确认通过' }));
      expect(
        await editor.findByRole('button', { name: '刷新核实结果' }),
      ).toBeInTheDocument();
      expect(editor.getByRole('button', { name: '确认通过' })).toBeDisabled();
      fireEvent.click(editor.getByRole('button', { name: '刷新核实结果' }));
      await waitFor(() =>
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
      );
      expect(
        await screen.findByText(outcome === 'conflict' ? '已撤回' : '已通过'),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: '通过申请' }),
      ).not.toBeInTheDocument();
      expect(writes(fetcher)).toHaveLength(1);
    },
  );

  it('does not offer review actions on terminal applications', async () => {
    mockClaims({ terminal: true });
    renderRoutes(`/property${claimPath}`);
    await screen.findByText('已通过');
    expect(
      screen.queryByRole('button', { name: '通过申请' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '驳回申请' }),
    ).not.toBeInTheDocument();
  });

  it('lists active bindings with masked phones and supports explicit revocation with a reason and version', async () => {
    const fetcher = mockClaims();
    const list = renderRoutes('/property/resident-house-bindings');
    expect(await screen.findByText('138****5678')).toBeInTheDocument();
    const request = fetcher.mock.calls.find(
      ([url]) =>
        new URL(String(url)).pathname === `${root}/resident-house-bindings`,
    )!;
    expect(new URL(String(request[0])).searchParams.get('status')).toBe(
      'active',
    );
    list.unmount();
    renderRoutes(`/property${bindingPath}`);
    await screen.findByText(binding.applicant_phone);
    fireEvent.click(screen.getByRole('button', { name: '撤销绑定' }));
    const editor = within(await screen.findByRole('dialog'));
    fireEvent.click(editor.getByRole('button', { name: '确认撤销' }));
    expect(await editor.findByText('请填写原因')).toBeInTheDocument();
    fireEvent.change(editor.getByLabelText('撤销原因'), {
      target: { value: '产权已转让' },
    });
    fireEvent.click(editor.getByRole('button', { name: '确认撤销' }));
    expect(await screen.findByText('物业已撤销')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '撤销绑定' }),
    ).not.toBeInTheDocument();
    expect(JSON.parse(String(writes(fetcher)[0][1]?.body))).toEqual({
      expected_row_version: 5,
      reason: '产权已转让',
    });
  });
});
