import dayjs, { type Dayjs } from 'dayjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { date as formatBusinessDate } from '../../src/features/property/presentation';
import {
  businessNow,
  businessToday,
  dateRangeFromInstants,
  dayAfterInstant,
  dayStartInstant,
  formatTime,
  pickerTimeToInstant,
  toPickerTime,
} from '../../src/shared/datetime';

afterEach(() => vi.useRealTimers());

describe('北京时间显示与业务日期', () => {
  it.each([
    '2026-10-31T16:30:45.123Z',
    '2026-11-01T00:30:45.123+08:00',
    '2026-10-31T09:30:45.123-07:00',
  ])('时间戳 %s 在不同浏览器时区都显示同一北京时间', (value) => {
    expect(formatTime(value)).toBe('2026-11-01 00:30');
  });

  it.each([undefined, null, '', 'invalid-timestamp'])(
    '缺失或非法时间 %s 显示占位',
    (value) => {
      expect(formatTime(value)).toBe('—');
    },
  );

  it.each([
    ['2026-10-31T15:59:59.999Z', '2026-10-31', '2026-11-01'],
    ['2026-10-31T16:00:00.000Z', '2026-11-01', '2026-12-01'],
    ['2026-12-31T16:00:00.000Z', '2027-01-01', '2027-02-01'],
  ])(
    '上海午夜附近 %s 使用正确业务日期和下月默认账期',
    (instant, today, nextMonth) => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date(instant));

      expect(businessToday()).toBe(today);
      expect(businessNow().format('YYYY-MM-DD')).toBe(today);
      expect(
        businessNow().add(1, 'month').startOf('month').format('YYYY-MM-DD'),
      ).toBe(nextMonth);
    },
  );

  it.each(['2026-03-08', '2026-11-01', '2011-12-30'])(
    '纯业务日期 %s 不随浏览器时区或夏令时偏移',
    (value) => {
      expect(formatBusinessDate(value)).toBe(value);
    },
  );
});

describe('审计时间选择器', () => {
  it('将选择器显示的时间解读为北京时间，而非浏览器本地时间', () => {
    const selected = dayjs('2026-10-27T09:15:33.456');

    expect(pickerTimeToInstant(selected)).toBe('2026-10-27T01:15:33.456Z');
  });

  it.each([
    ['2026-03-07T18:30:00.123Z', '2026-03-08 02:30:00.123'],
    ['2026-10-31T17:30:00.456Z', '2026-11-01 01:30:00.456'],
    ['2026-12-31T16:00:00.999Z', '2027-01-01 00:00:00.999'],
  ])(
    '还原并重提 %s 保留瞬间和毫秒，且不受美国夏令时影响',
    (instant, displayed) => {
      const selected = toPickerTime(instant);

      expect(selected?.format('YYYY-MM-DD HH:mm:ss.SSS')).toBe(displayed);
      expect(pickerTimeToInstant(selected!)).toBe(instant);
    },
  );

  it('非法时间不生成选择器值', () => {
    expect(toPickerTime('invalid-timestamp')).toBeNull();
  });

  it.each([
    {
      action: '将小时和分钟改至美国夏令时缺失时段',
      instant: '2026-03-07T17:15:22.123Z',
      edit: (value: Dayjs) => value.hour(2).minute(30),
      displayed: '2026-03-08 02:30:22.123',
      submitted: '2026-03-07T18:30:22.123Z',
    },
    {
      action: '将日期改至美国夏令时开始日',
      instant: '2026-03-06T18:30:22.123Z',
      edit: (value: Dayjs) => value.date(8),
      displayed: '2026-03-08 02:30:22.123',
      submitted: '2026-03-07T18:30:22.123Z',
    },
    {
      action: '将月份改至美国夏令时开始月',
      instant: '2026-02-07T18:30:22.123Z',
      edit: (value: Dayjs) => value.month(2),
      displayed: '2026-03-08 02:30:22.123',
      submitted: '2026-03-07T18:30:22.123Z',
    },
    {
      action: '将小时和分钟改至美国夏令时重复时段',
      instant: '2026-10-31T19:15:22.123Z',
      edit: (value: Dayjs) => value.hour(1).minute(30),
      displayed: '2026-11-01 01:30:22.123',
      submitted: '2026-10-31T17:30:22.123Z',
    },
  ])(
    '$action 后按用户选择的北京时间提交',
    ({ instant, edit, displayed, submitted }) => {
      const selected = edit(toPickerTime(instant)!);

      expect(selected.format('YYYY-MM-DD HH:mm:ss.SSS')).toBe(displayed);
      expect(pickerTimeToInstant(selected)).toBe(submitted);
    },
  );
});

describe('整日查询的左闭右开区间', () => {
  it.each([
    ['2026-10-27', '2026-10-26T16:00:00.000Z', '2026-10-27T16:00:00.000Z'],
    ['2026-12-31', '2026-12-30T16:00:00.000Z', '2026-12-31T16:00:00.000Z'],
    ['2028-02-29', '2028-02-28T16:00:00.000Z', '2028-02-29T16:00:00.000Z'],
    ['2026-03-08', '2026-03-07T16:00:00.000Z', '2026-03-08T16:00:00.000Z'],
    ['2026-11-01', '2026-10-31T16:00:00.000Z', '2026-11-01T16:00:00.000Z'],
  ])(
    '日期 %s 从上海当日零点到次日零点，覆盖最后一毫秒',
    (date, from, before) => {
      expect(dayStartInstant(date)).toBe(from);
      expect(dayAfterInstant(date)).toBe(before);
      const selected = dayjs(date);
      expect(dayStartInstant(selected)).toBe(from);
      expect(dayAfterInstant(selected)).toBe(before);
    },
  );

  it.each([
    [
      '2026-10-26T16:00:00.000Z',
      '2026-10-27T16:00:00.000Z',
      '2026-10-27',
      '2026-10-27',
    ],
    [
      '2026-10-30T16:00:00.000Z',
      '2026-11-02T16:00:00.000Z',
      '2026-10-31',
      '2026-11-02',
    ],
    [
      '2026-03-06T16:00:00.000Z',
      '2026-03-09T16:00:00.000Z',
      '2026-03-07',
      '2026-03-09',
    ],
  ])(
    '恢复区间 %s 至 %s 再次查询不增加一天',
    (from, before, firstDay, lastDay) => {
      const dates = dateRangeFromInstants(from, before);

      expect(dates?.[0].format('YYYY-MM-DD')).toBe(firstDay);
      expect(dates?.[1].format('YYYY-MM-DD')).toBe(lastDay);
      expect(dayStartInstant(dates![0])).toBe(from);
      expect(dayAfterInstant(dates![1])).toBe(before);
    },
  );

  it.each([
    [undefined, '2026-10-27T16:00:00.000Z'],
    ['2026-10-26T16:00:00.000Z', undefined],
    ['invalid-timestamp', '2026-10-27T16:00:00.000Z'],
    ['2026-10-26T16:00:00.000Z', 'invalid-timestamp'],
  ])('缺失或非法区间 %s 至 %s 不生成选择器值', (from, before) => {
    expect(dateRangeFromInstants(from, before)).toBeNull();
  });
});
