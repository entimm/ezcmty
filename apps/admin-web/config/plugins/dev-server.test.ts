import type { IApi } from '@umijs/max';
import { afterEach, describe, expect, it, vi } from 'vitest';

import devServer, { configureDevServer } from './dev-server';

afterEach(() => vi.unstubAllEnvs());

describe('fixed development listener', () => {
  it('binds loopback and rejects Umi port fallback', () => {
    vi.stubEnv('HOST', '0.0.0.0');
    vi.stubEnv('PORT', '9000');
    const modifyAppData = vi.fn();
    devServer({ name: 'dev', modifyAppData } as unknown as IApi);
    expect(process.env.HOST).toBe('127.0.0.1');
    expect(process.env.PORT).toBe('5173');
    const { fn, stage } = modifyAppData.mock.calls[0][0];
    expect(stage).toBe(Number.POSITIVE_INFINITY);
    expect(fn({ port: 5173, host: '0.0.0.0' })).toMatchObject({
      port: 5173,
      host: '127.0.0.1',
    });
    expect(() => fn({ port: 5174 })).toThrow('5173');
  });

  it('leaves setup and production build commands unaffected', () => {
    const modifyAppData = vi.fn();
    configureDevServer(
      { name: 'build', modifyAppData } as unknown as IApi,
      5173,
    );
    expect(modifyAppData).not.toHaveBeenCalled();
  });
});
