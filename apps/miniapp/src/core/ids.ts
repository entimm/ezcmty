export function newKey(): string {
  return (
    'mini_' +
    Date.now().toString(36) +
    '_' +
    Math.random().toString(36).slice(2, 14)
  );
}
