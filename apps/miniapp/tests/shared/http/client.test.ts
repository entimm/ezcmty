import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  ApiError,
  errorText,
  request,
  StaleSessionError,
} from '../../../src/shared/http/client';

interface Pending {
  fail: (error: { errMsg: string; errno?: number }) => void;
  complete: () => void;
}

let pending: Pending;
const realtimeError = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.stubGlobal('wx', {
    request: (options: Pending) => {
      pending = options;
      return { abort: vi.fn() };
    },
    getRealtimeLogManager: () => ({ error: realtimeError }),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it.each([
  'request:fail url not in domain list',
  'request:fail ssl hand shake error',
  'request:fail timeout',
])('preserves the diagnostic reason for %s', async (errMsg) => {
  const result = request<void>(
    'https://api.example.test',
    '/resident-sessions',
    {
      method: 'POST',
    },
  ).catch((error: unknown) => error);
  pending.fail({ errMsg, errno: 600001 });
  pending.complete();

  const failure = (await result) as ApiError;
  expect(failure).toBeInstanceOf(ApiError);
  expect(failure.diagnostics).toEqual({
    method: 'POST',
    url: 'https://api.example.test/v1/resident-sessions',
    errMsg,
    errno: 600001,
  });
  expect(errorText(failure)).toBe(
    '网络连接失败，请检查网络后重试\nerrMsg: ' +
      errMsg +
      '\nerrno: 600001\nPOST https://api.example.test/v1/resident-sessions',
  );
});

it('keeps request credentials out of diagnostics and logs', async () => {
  const result = request<void>(
    'https://api.example.test',
    '/resident-sessions?code=private-code#private-fragment',
    {
      method: 'POST',
      token: 'private-token',
      data: { code: 'private-code' },
    },
  ).catch((error: unknown) => error);
  pending.fail({
    errMsg:
      'request:fail https://api.example.test/v1/resident-sessions?code=private-code&token=private-token#private-fragment',
  });
  pending.complete();

  const failure = (await result) as ApiError;
  expect(failure.diagnostics?.errMsg).toBe(
    'request:fail https://api.example.test/v1/resident-sessions',
  );
  expect(console.error).toHaveBeenCalledOnce();
  expect(realtimeError).toHaveBeenCalledOnce();
  const output = JSON.stringify({
    message: errorText(failure),
    diagnostics: failure.diagnostics,
    console: vi.mocked(console.error).mock.calls,
    realtime: realtimeError.mock.calls,
  });
  expect(output).not.toContain('private-code');
  expect(output).not.toContain('private-token');
  expect(output).not.toContain('private-fragment');
});

it.each([undefined, 0])(
  'formats network diagnostics with optional errno %s and a recovery message',
  (errno) => {
    const failure = new ApiError(0, 'network', '网络错误', '', {
      method: 'POST',
      url: 'https://api.example.test/v1/claims',
      errMsg: 'request:fail timeout',
      errno,
    });
    const message = errorText(failure, '提交结果尚未确认，请重试原请求。');
    expect(message).toContain('提交结果尚未确认，请重试原请求。\nerrMsg:');
    expect(message).toContain('request:fail timeout');
    if (errno === undefined) expect(message).not.toContain('errno:');
    else expect(message).toContain('errno: 0');
  },
);

it('keeps stale session errors silent even with a recovery message', () => {
  expect(errorText(new StaleSessionError(), '请重试')).toBe('');
});

it('does not expose internal errors as network diagnostics', () => {
  expect(errorText(new Error('internal secret'))).toBe(
    '暂时无法完成，请稍后重试',
  );
  expect(errorText(new ApiError(422, 'invalid', '请检查填写内容'))).toBe(
    '请检查填写内容',
  );
});

it('preserves the original diagnostics when realtime reporting fails', async () => {
  Object.assign(wx, {
    getRealtimeLogManager: () => {
      throw new Error('log reporting unavailable');
    },
  });
  const result = request<void>(
    'https://api.example.test',
    '/resident-sessions',
  ).catch((error: unknown) => error);
  pending.fail({ errMsg: 'request:fail timeout', errno: 600001 });

  expect(await result).toMatchObject({
    code: 'network',
    diagnostics: { errMsg: 'request:fail timeout', errno: 600001 },
  });
});
