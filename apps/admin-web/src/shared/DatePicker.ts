import dayjs from 'dayjs';
import { DatePicker as AntDatePicker } from 'antd';
import dayjsConfig from '@rc-component/picker/generate/dayjs';
import { businessNow } from './datetime';

// Keep calendar input, Today and Now in the same Beijing fields as displayed values.
export const DatePicker = AntDatePicker.generatePicker({
  ...dayjsConfig,
  getNow: businessNow,
  getFixedDate: (date) => dayjs.utc(date),
  locale: {
    ...dayjsConfig.locale,
    parse: (locale, text, formats) => {
      for (const format of formats) {
        if (format.includes('wo') || format.includes('Wo')) {
          const value = dayjsConfig.locale.parse(locale, text, [format]);
          if (value) return dayjs.utc(value.format('YYYY-MM-DD'));
          continue;
        }
        const value = dayjs
          .utc(text, format, true)
          .locale(locale.toLowerCase().replace('_', '-'));
        if (value.isValid()) return value;
      }
      return null;
    },
  },
});
