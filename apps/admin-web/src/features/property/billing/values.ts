import type { Rule } from 'antd/es/form';

export function parseMoney(value: string, positive = false): number {
  const text = value.trim();
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(text))
    throw new Error('请输入非负金额，最多两位小数');
  const [whole, fraction = ''] = text.split('.');
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  if (cents > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error('金额超过支持范围');
  if (positive && cents === 0n) throw new Error('收款金额必须大于 0');
  return Number(cents);
}
export function money(cents: number): string {
  const amount = BigInt(cents);
  const absolute = amount < 0n ? -amount : amount;
  return `${amount < 0n ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`;
}
export const yuan = (cents: number) => `¥${money(cents)}`;
export const usageLabels = {
  residential: '住宅',
  commercial: '商业',
  office: '办公',
  other: '其他',
};
export const actionLabels = {
  create: '建账',
  update: '修改资料',
  receipt: '登记收款',
  correct_receipt: '收款纠错',
  reverse_receipt: '撤销误登记',
  void: '作废',
};
export const monthRule: Rule = {
  validator: async (_, value: unknown) => {
    if (
      typeof value !== 'string' ||
      !/^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(value) ||
      value === '9999-12'
    )
      throw new Error('请选择有效月份');
  },
};
export const validMonth = (value?: string) =>
  !!value &&
  /^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(value) &&
  value !== '9999-12';
export const textRule = (max: number, required = false): Rule => ({
  validator: async (_, value: unknown) => {
    const text = typeof value === 'string' ? value.trim() : '';
    if (required && !text) throw new Error('请填写原因');
    if ([...text].length > max) throw new Error(`最多 ${max} 个字符`);
  },
});
export const moneyRule = (positive = false): Rule => ({
  validator: async (_, value: unknown) => {
    parseMoney(typeof value === 'string' ? value : '', positive);
  },
});
export function businessToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}
export const receiptDateRule: Rule = {
  validator: async (_, value: unknown) => {
    if (typeof value === 'string' && value && value > businessToday())
      throw new Error('收款日期不能在未来');
  },
};
