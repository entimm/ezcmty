import { beforeEach, describe, expect, it, vi } from 'vitest';
const session = vi.hoisted(() => ({
  owner: 'resident-a' as string | null,
  revision: 1,
  listeners: new Set<() => void>(),
}));
vi.mock('../../src/core/session', () => ({
  currentCredential: () =>
    session.owner
      ? { userId: session.owner, token: 'token', expiresAt: '2026-12-01' }
      : null,
  sessionRevision: () => session.revision,
  onSessionReset: (listener: () => void) => {
    session.listeners.add(listener);
    return () => {
      session.listeners.delete(listener);
    };
  },
}));
import { PageScope } from '../../src/packages/resident/page-state';
beforeEach(() => {
  session.owner = 'resident-a';
  session.revision = 1;
  session.listeners.clear();
});
describe('可见页面与本人响应隔离', () => {
  it('较晚发起的加载取代旧响应', () => {
    const scope = new PageScope();
    scope.enter();
    const old = scope.next();
    const latest = scope.next();
    expect(old()).toBe(false);
    expect(latest()).toBe(true);
  });
  it('隐藏和再次显示之间，旧响应不能回填', () => {
    const scope = new PageScope();
    scope.enter();
    const old = scope.next();
    scope.leave();
    scope.enter();
    expect(old()).toBe(false);
  });
  it('跨居民响应不能回填', () => {
    const scope = new PageScope();
    scope.enter();
    const old = scope.next();
    session.owner = 'resident-b';
    expect(old()).toBe(false);
    expect(scope.enter()).toBe(false);
  });
  it('同居民重新登录换代后，旧响应也失效', () => {
    const scope = new PageScope();
    scope.enter();
    const old = scope.next();
    session.revision++;
    expect(old()).toBe(false);
    expect(scope.enter()).toBe(false);
  });
  it('401触发清理回调并告知当前页面可见', () => {
    const scope = new PageScope();
    const clear = vi.fn();
    scope.watch(clear);
    scope.enter();
    const old = scope.next();
    session.owner = null;
    session.revision++;
    session.listeners.forEach((listener) => listener());
    expect(old()).toBe(false);
    expect(clear).toHaveBeenCalledWith(true);
    scope.dispose();
    expect(session.listeners.size).toBe(0);
  });
  it('隐藏页面清除私有数据，不额外触发可见页登录导航', () => {
    const scope = new PageScope();
    const clear = vi.fn();
    scope.watch(clear);
    scope.enter();
    scope.leave();
    session.listeners.forEach((listener) => listener());
    expect(clear).toHaveBeenCalledWith(false);
  });
});
