import '@testing-library/jest-dom/vitest';
import { useState } from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

type Navigation = typeof import('../../src/app/navigation');
let navigation: Navigation | undefined;
let serial = 0;
afterEach(async () => {
  cleanup();
  navigation?.setNavigationGuard();
  await act(async () => {
    await Promise.resolve();
  });
});

async function show() {
  cleanup();
  navigation?.setNavigationGuard();
  navigation = await import('../../src/app/navigation');
  const api = navigation;
  const prefix = '/navigation-' + String(++serial);
  api.navigate(prefix + '/start', true);
  function Editor() {
    const [draft, setDraft] = useState('');
    return (
      <input
        aria-label="未保存内容"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
    );
  }
  function Location() {
    const address = api.useAddress();
    return (
      <>
        <output data-testid="address">{address}</output>
        <Editor key={address} />
      </>
    );
  }
  render(<Location />);
  let pending: (() => void) | undefined;
  const guard = vi.fn((action: () => void) => {
    pending = action;
  });
  return {
    prefix,
    api,
    guard,
    setDirty: (value: boolean) => {
      api.setNavigationGuard(value ? guard : undefined);
    },
    confirm: () => {
      const action = pending;
      pending = undefined;
      action?.();
    },
    cancel: () => {
      pending = undefined;
    },
  };
}
async function at(path: string) {
  await waitFor(() => {
    expect(window.location.pathname + window.location.search).toBe(path);
    expect(screen.getByTestId('address')).toHaveTextContent(path);
  });
}

describe('浏览器历史导航与未保存保护', () => {
  it.each([false, true])(
    '页面跳转 replace=%s 取消时保留输入，确认后沿原操作继续',
    async (replace) => {
      const view = await show();
      const start = view.prefix + '/start',
        target = view.prefix + '/target?page=3';
      const originalLength = window.history.length;
      const input = screen.getByRole('textbox', { name: '未保存内容' });
      fireEvent.change(input, { target: { value: '尚未提交' } });
      view.setDirty(true);
      act(() => view.api.navigate(target, replace));
      await at(start);
      view.cancel();
      expect(input).toHaveValue('尚未提交');
      expect(screen.getByRole('textbox', { name: '未保存内容' })).toBe(input);
      act(() => view.api.navigate(target, replace));
      act(() => view.confirm());
      await at(target);
      expect(view.guard).toHaveBeenCalledTimes(2);
      expect(window.history.length).toBe(originalLength + (replace ? 0 : 1));
    },
  );
  it('替换当前页面后，后退跳过被替换地址并保留前进目标', async () => {
    const view = await show();
    const first = view.prefix + '/first',
      replaced = view.prefix + '/replaced',
      target = view.prefix + '/target?tab=owners';
    act(() => {
      view.api.navigate(first);
      view.api.navigate(replaced);
      view.api.navigate(target, true);
    });
    await at(target);
    act(() => window.history.back());
    await at(first);
    act(() => window.history.forward());
    await at(target);
  });
  it('仅未保存时拦截刷新，清除工作区拦截后旧确认不能跳转', async () => {
    const view = await show();
    const unload = () => {
      const event = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(unload()).toBe(false);
    view.setDirty(true);
    expect(unload()).toBe(true);
    act(() => view.api.navigate(view.prefix + '/stale'));
    view.api.setNavigationGuard();
    expect(unload()).toBe(false);
    act(() => view.confirm());
    await at(view.prefix + '/start');
    act(() => view.api.navigate(view.prefix + '/new-session'));
    await at(view.prefix + '/new-session');
    expect(view.guard).toHaveBeenCalledOnce();
  });
  it('没有未保存内容时多次后退前进沿原历史移动，不弹确认也不形成循环', async () => {
    const view = await show();
    const first = view.prefix + '/first?search=锦城',
      second = view.prefix + '/second?page=2',
      third = view.prefix + '/third';
    act(() => {
      view.api.navigate(first);
      view.api.navigate(second);
      view.api.navigate(third);
    });
    const originalLength = window.history.length;
    await at(third);
    act(() => window.history.back());
    await at(second);
    act(() => window.history.back());
    await at(first.replace('锦城', encodeURIComponent('锦城')));
    act(() => window.history.forward());
    await at(second);
    act(() => window.history.forward());
    await at(third);
    act(() => window.history.back());
    await at(second);
    act(() => window.history.back());
    await at(first.replace('锦城', encodeURIComponent('锦城')));
    expect(view.guard).not.toHaveBeenCalled();
    expect(window.history.length).toBe(originalLength);
  });
  it('后退取消后保留原 URL 和编辑组件，再次后退仍指向同一条历史', async () => {
    const view = await show();
    const first = view.prefix + '/list?status=enabled',
      edit = view.prefix + '/edit';
    act(() => {
      view.api.navigate(first);
      view.api.navigate(edit);
    });
    fireEvent.change(screen.getByRole('textbox', { name: '未保存内容' }), {
      target: { value: '等待提交的资料' },
    });
    const originalInput = screen.getByRole('textbox', { name: '未保存内容' });
    view.setDirty(true);
    act(() => window.history.back());
    await waitFor(() => expect(view.guard).toHaveBeenCalledOnce());
    await at(edit);
    view.cancel();
    expect(screen.getByRole('textbox', { name: '未保存内容' })).toBe(
      originalInput,
    );
    expect(originalInput).toHaveValue('等待提交的资料');
    act(() => window.history.back());
    await waitFor(() => expect(view.guard).toHaveBeenCalledTimes(2));
    await at(edit);
    act(() => view.confirm());
    await at(first);
  });
  it('确认放弃后准确返回原目标，并保留前进历史而不额外插入页面', async () => {
    const view = await show();
    const first = view.prefix + '/list?search=unit&page=4',
      edit = view.prefix + '/detail';
    act(() => {
      view.api.navigate(first);
      view.api.navigate(edit);
    });
    view.setDirty(true);
    act(() => window.history.back());
    await waitFor(() => expect(view.guard).toHaveBeenCalledOnce());
    await at(edit);
    act(() => view.confirm());
    await at(first);
    act(() => window.history.forward());
    await at(edit);
    act(() => window.history.back());
    await at(first);
    expect(view.guard).toHaveBeenCalledOnce();
  });
  it('前进遇到未保存内容时先恢复原页，确认后仍前进到原始目标', async () => {
    const view = await show();
    const first = view.prefix + '/list',
      second = view.prefix + '/detail?tab=owners',
      third = view.prefix + '/review';
    act(() => {
      view.api.navigate(first);
      view.api.navigate(second);
      view.api.navigate(third);
    });
    act(() => window.history.back());
    await at(second);
    fireEvent.change(screen.getByRole('textbox', { name: '未保存内容' }), {
      target: { value: '本页备注' },
    });
    view.setDirty(true);
    act(() => window.history.forward());
    await waitFor(() => expect(view.guard).toHaveBeenCalledOnce());
    await at(second);
    expect(screen.getByRole('textbox', { name: '未保存内容' })).toHaveValue(
      '本页备注',
    );
    act(() => view.confirm());
    await at(third);
    act(() => window.history.back());
    await at(second);
    act(() => window.history.back());
    await at(first);
  });
  it('跨多条历史后退时保留准确的目标与查询条件', async () => {
    const view = await show();
    const first = view.prefix + '/first',
      target = view.prefix + '/target?page=7',
      third = view.prefix + '/third',
      edit = view.prefix + '/edit';
    act(() => {
      view.api.navigate(first);
      view.api.navigate(target);
      view.api.navigate(third);
      view.api.navigate(edit);
    });
    view.setDirty(true);
    act(() => window.history.go(-2));
    await waitFor(() => expect(view.guard).toHaveBeenCalledOnce());
    await at(edit);
    act(() => view.confirm());
    await at(target);
    act(() => window.history.forward());
    await at(third);
    act(() => window.history.forward());
    await at(edit);
  });
});
