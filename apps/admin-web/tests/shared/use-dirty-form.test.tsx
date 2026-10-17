import {
  act,
  fireEvent,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { App, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { history } from '@umijs/max';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useDirtyForm } from '@/shared/hooks/use-dirty-form';

function wrapper({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
      <App>{children}</App>
    </ConfigProvider>
  );
}

function navigation() {
  type Blocker = (transition: { retry: () => void }) => void;
  const blockers = new Set<Blocker>();
  vi.spyOn(history, 'block').mockImplementation((callback) => {
    const blocker = callback as Blocker;
    blockers.add(blocker);
    return () => blockers.delete(blocker);
  });
  const arrived = vi.fn();
  const navigate = () => {
    if (blockers.size) {
      for (const blocker of blockers) blocker({ retry: navigate });
    } else arrived();
  };
  return { navigate, arrived };
}

function unload() {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event;
}

afterEach(() => vi.restoreAllMocks());

describe('unsaved form guards', () => {
  it('allows immediate navigation and unloading after a successful save', () => {
    const { navigate, arrived } = navigation();
    const { result } = renderHook(useDirtyForm, { wrapper });
    act(() => result.current.changed());

    act(() => {
      result.current.reset();
      navigate();
      expect(arrived).toHaveBeenCalledOnce();
      expect(unload().defaultPrevented).toBe(false);
    });

    expect(arrived).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole('dialog', { name: '放弃未保存的修改？' }),
    ).not.toBeInTheDocument();
  });

  it('requires confirmation to navigate away from unsaved changes', async () => {
    const { navigate, arrived } = navigation();
    const { result } = renderHook(useDirtyForm, { wrapper });
    act(() => result.current.changed());
    expect(unload().defaultPrevented).toBe(true);

    act(navigate);
    expect(
      await screen.findByRole('dialog', { name: '放弃未保存的修改？' }),
    ).toBeInTheDocument();
    expect(arrived).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确 定' }));
    await waitFor(() => expect(arrived).toHaveBeenCalledOnce());
  });

  it('still confirms closing an unsaved form after another edit', async () => {
    const done = vi.fn();
    const { result } = renderHook(useDirtyForm, { wrapper });
    act(() => result.current.changed());
    act(() => result.current.reset());
    act(() => result.current.changed());
    expect(unload().defaultPrevented).toBe(true);

    act(() => result.current.close(done));
    expect(
      await screen.findByRole('dialog', { name: '放弃未保存的修改？' }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '取 消' }));
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: '放弃未保存的修改？' }),
      ).not.toBeInTheDocument(),
    );
    expect(done).not.toHaveBeenCalled();
    expect(unload().defaultPrevented).toBe(true);

    act(() => result.current.close(done));
    fireEvent.click(await screen.findByRole('button', { name: '确 定' }));
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
  });

  it('removes navigation and unload guards when the form unmounts', () => {
    const { navigate, arrived } = navigation();
    const { result, unmount } = renderHook(useDirtyForm, { wrapper });
    act(() => result.current.changed());
    unmount();

    act(navigate);
    expect(arrived).toHaveBeenCalledOnce();
    expect(unload().defaultPrevented).toBe(false);
  });
});
