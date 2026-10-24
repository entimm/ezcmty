import { describe, expect, it } from 'vitest';
import {
  addressParts,
  bindingView,
  claimView,
  houseClaimConflict,
  loadAll,
} from '../../src/packages/resident/presentation';
import type { Binding, Claim } from '../../src/core/types';
const binding: Binding = {
  id: 'binding',
  community_id: 'community',
  house_id: 'house',
  claim_application_id: 'claim',
  house_label_snapshot: '梧桐里／一期／3栋／1单元／1202',
  status: 'active',
  effective_enabled: true,
  granted_at: '2026-10-24T02:00:00Z',
  ended_at: null,
  end_reason: null,
  row_version: 1,
  created_at: '2026-10-24T02:00:00Z',
  updated_at: '2026-10-24T02:00:00Z',
};
const claim: Claim = {
  id: 'claim',
  community_id: 'community',
  house_id: 'house',
  house_label_snapshot: binding.house_label_snapshot,
  applicant_name: '陈雨桐',
  applicant_phone: '13800136028',
  applicant_remark: null,
  status: 'approved',
  review_reason: null,
  reviewed_at: '2026-10-24T03:00:00Z',
  cancelled_at: null,
  row_version: 1,
  created_at: '2026-10-24T02:00:00Z',
  updated_at: '2026-10-24T03:00:00Z',
};
describe('居民展示与完整分页', () => {
  it('按服务端路径显示完整位置，允许省略层级', () => {
    expect(addressParts('云栖花园／2栋／602')).toEqual({
      community: '云栖花园',
      room: '2栋 · 602',
    });
    expect(addressParts(binding.house_label_snapshot).room).toBe(
      '一期 · 3栋 · 1单元 · 1202',
    );
  });
  it('停用的active授权不可继续房屋业务，但仍可主动解绑', () => {
    const view = bindingView({ ...binding, effective_enabled: false });
    expect(view).toMatchObject({
      enabled: false,
      history: false,
      statusText: '暂不可用',
    });
  });
  it.each(['released', 'revoked'] as const)(
    '历史%s即使意外携带enabled也不会被当成有效授权',
    (status) => {
      expect(
        bindingView({ ...binding, status, effective_enabled: true }),
      ).toMatchObject({ enabled: false, history: true });
    },
  );
  it('已通过申请只表达审核历史，不在展示转换中授予房屋权限', () => {
    const view = claimView(claim);
    expect(view.statusText).toBe('已通过');
    expect(view.description).toContain('有效授权');
    expect(view).not.toHaveProperty('enabled');
    expect(view.phone).toBe('138 **** 6028');
  });
  it('禁止对已绑定或待审房屋新建重复申请，历史授权不阻断重新认领', () => {
    expect(
      houseClaimConflict(
        'house',
        [{ ...binding, effective_enabled: false }],
        [],
      ),
    ).toContain('已绑定');
    expect(
      houseClaimConflict('house', [], [{ ...claim, status: 'pending' }]),
    ).toContain('待审核');
    expect(
      houseClaimConflict(
        'house',
        [{ ...binding, status: 'released' }],
        [claim],
      ),
    ).toBe('');
  });
  it('撤回终态显示撤回时间，不使用审核时间', () => {
    expect(
      claimView({
        ...claim,
        status: 'cancelled',
        cancelled_at: '2026-10-24T05:30:00Z',
      }).finished,
    ).toBe('2026-10-24 13:30');
  });
  it('首页总额和筛选需要完整分页，不能只取第一页', async () => {
    const pages: number[] = [];
    const rows = await loadAll(async (page) => {
      pages.push(page);
      return { items: [page], total: 3, page, page_size: 1 };
    });
    expect(rows).toEqual([1, 2, 3]);
    expect(pages).toEqual([1, 2, 3]);
  });
  it('后续分页错误不发布不完整新快照，页面可保留已有成功数据', async () => {
    await expect(
      loadAll(async (page) => {
        if (page === 2) throw new Error('离线');
        return { items: [1], total: 2, page, page_size: 1 };
      }),
    ).rejects.toThrow('离线');
  });
});
