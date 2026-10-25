export const propertyOrganizationPermissions = [
  'property.housing.read',
  'property.bill.read',
  'property.resident_access.read',
  'property.payment.read',
  'property.system.read',
];

export function canViewPropertyOrganization(
  can: (permission: string) => boolean,
) {
  return propertyOrganizationPermissions.some(can);
}
