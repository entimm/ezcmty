import type { Scope } from '../types';

export function canImport(
  scope: Scope,
  can: (permission: string) => boolean,
  action: string,
  type?: string,
) {
  if (scope !== 'property') return false;
  const resources = type
    ? type === 'bills'
      ? ['bill']
      : ['houses', 'house_owners'].includes(type)
        ? ['housing']
        : type === 'property_fee_basis_versions'
          ? ['fee_basis']
          : []
    : ['housing', 'bill', 'fee_basis'];
  const operation = ['read', 'download', 'generate_error_file'].includes(action)
    ? 'read'
    : 'manage';
  return resources.some((resource) =>
    can(
      `property.${operation === 'read' && resource === 'fee_basis' ? 'bill' : resource}.${operation}`,
    ),
  );
}
