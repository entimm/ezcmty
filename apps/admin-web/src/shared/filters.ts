export function parseEnabled(value: string | null) {
  return value === 'true' ? true : value === 'false' ? false : undefined;
}
