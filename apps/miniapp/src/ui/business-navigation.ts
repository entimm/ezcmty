export interface BusinessEntry {
  home: string;
  accepts(url: string): boolean;
}
const residentHome = '/packages/resident/pages/home/index';
export const businessEntries: Readonly<Record<string, BusinessEntry>> = {
  resident: {
    home: residentHome,
    accepts: (url) =>
      /^\/packages\/resident\/pages\/(?:home|houses|claims|profile|claim|claim-detail|house-detail|bills|bill-detail|payment-confirm|payment-orders|payment-detail)\/index(?:\?(?:id|house_id|community_id)=[0-9a-f-]{36}(?:&(?:house_id|community_id)=[0-9a-f-]{36})?)?$/.test(
        url,
      ),
  },
};
export function entryFor(type: string): BusinessEntry | undefined {
  return Object.prototype.hasOwnProperty.call(businessEntries, type)
    ? businessEntries[type]
    : undefined;
}
