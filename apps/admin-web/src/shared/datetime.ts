import dayjs, { type Dayjs } from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import 'dayjs/locale/zh-cn';

dayjs.extend(utc);
dayjs.extend(timezone);

const timeZone = 'Asia/Shanghai';
const calendarFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  fractionalSecondDigits: 3,
  hourCycle: 'h23',
});

// Calendar values carry Beijing fields in UTC mode to avoid browser DST normalization.
// Convert them through pickerTimeToInstant before sending a timestamp to the API.
export function businessNow() {
  return toPickerTime(new Date().toISOString())!.locale('zh-cn');
}

export function businessToday() {
  return businessNow().format('YYYY-MM-DD');
}

export function toPickerTime(value: string) {
  const instant = dayjs.utc(value);
  if (!instant.isValid()) return null;
  const fields = Object.fromEntries(
    calendarFormatter
      .formatToParts(instant.toDate())
      .map(({ type, value }) => [type, value]),
  );
  return dayjs.utc(
    `${fields.year}-${fields.month}-${fields.day}T${fields.hour}:${fields.minute}:${fields.second}.${fields.fractionalSecond}`,
  );
}

export function formatTime(value?: string | null) {
  return value ? (toPickerTime(value)?.format('YYYY-MM-DD HH:mm') ?? '—') : '—';
}

export function pickerTimeToInstant(value: Dayjs) {
  // Picker fields represent Beijing wall time, regardless of the browser's zone.
  return dayjs
    .tz(value.format('YYYY-MM-DDTHH:mm:ss.SSS'), timeZone)
    .toISOString();
}

export function dayStartInstant(value: string | Dayjs) {
  const date = typeof value === 'string' ? value : value.format('YYYY-MM-DD');
  return dayjs.tz(date, timeZone).toISOString();
}

export function dayAfterInstant(value: string | Dayjs) {
  const date = typeof value === 'string' ? value : value.format('YYYY-MM-DD');
  return dayStartInstant(dayjs.utc(date).add(1, 'day').format('YYYY-MM-DD'));
}

export function dateRangeFromInstants(
  from?: string,
  before?: string,
): [Dayjs, Dayjs] | null {
  if (!from || !before) return null;
  const start = toPickerTime(from),
    end = toPickerTime(before);
  if (!start || !end || !end.isAfter(start)) return null;
  return [start.startOf('day'), end.subtract(1, 'millisecond').startOf('day')];
}
