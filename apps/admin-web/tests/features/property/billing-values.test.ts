import { describe, expect, it } from 'vitest';
import {
  money,
  parseMoney,
  textRule,
} from '@/features/property/billing/values';

function validateReason(value: string) {
  const rule = textRule(1000, true) as {
    validator: (rule: unknown, value: unknown) => Promise<void>;
  };
  return rule.validator({}, value);
}
describe('billing values', () => {
  it.each([
    ['0', 0],
    ['0.01', 1],
    ['1.10', 110],
    ['90071992547409.91', Number.MAX_SAFE_INTEGER],
  ])('parses %s without floating point rounding', (text, cents) => {
    expect(parseMoney(text)).toBe(cents);
    expect(parseMoney(money(cents))).toBe(cents);
  });
  it.each(['-1', '1.001', '1e3', '90071992547409.92', 'NaN', '01.00'])(
    'rejects invalid or unsafe amount %s',
    (value) => expect(() => parseMoney(value)).toThrow(),
  );
  it('rejects zero for a receipt and retains it for a receivable', () => {
    expect(parseMoney('0')).toBe(0);
    expect(() => parseMoney('0', true)).toThrow();
  });
  it('counts Unicode codepoints after trimming and never truncates', async () => {
    await expect(
      validateReason(` ${'🏠'.repeat(1000)} `),
    ).resolves.toBeUndefined();
    await expect(validateReason('🏠'.repeat(1001))).rejects.toThrow('1000');
    await expect(validateReason(' \n ')).rejects.toThrow('原因');
  });
});
