import type { Page } from './types';
/** Load each server page before offering a complete choice list. */
export async function allOptions<T extends { id: string }>(
  read: (page: number) => Promise<Page<T>>,
): Promise<T[]> {
  const items = new Map<string, T>();
  for (let page = 1; ; page++) {
    const result = await read(page);
    const before = items.size;
    result.items.forEach((item) => items.set(item.id, item));
    if (items.size >= result.total) return [...items.values()];
    if (items.size === before)
      throw new Error('选项列表加载不完整，请刷新后重试');
  }
}
