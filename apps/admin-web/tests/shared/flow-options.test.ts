import { describe, expect, it, vi } from 'vitest';
import { allOptions } from '../../src/shared/imports/options';
describe('完整范围选项', () => {
  it('持续读取超过首个100条的服务端分页，不遗漏后续公司或小区', async () => {
    const read = vi.fn(async (page: number) => ({
      items: Array.from({ length: page === 1 ? 100 : 2 }, (_, i) => ({
        id: String((page - 1) * 100 + i),
        name: `选项${i}`,
      })),
      page,
      page_size: 100,
      total: 102,
    }));
    const items = await allOptions(read);
    expect(items).toHaveLength(102);
    expect(items[101].id).toBe('101');
    expect(read.mock.calls).toEqual([[1], [2]]);
  });
  it('服务端出现空页而总量尚未读取完时明确失败，不把不完整范围交付给用户', async () => {
    await expect(
      allOptions(async () => ({
        items: [],
        page: 1,
        page_size: 100,
        total: 2,
      })),
    ).rejects.toThrow('选项列表加载不完整');
  });
});
