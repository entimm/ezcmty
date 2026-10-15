import type { Page } from '../../../shared/api/admin';
import { queryString } from '../../../shared/api/query-string';
import { createJsonWriter } from '../../../shared/api/write';
import type { AdminRequest } from '../../../shared/request-client';

export type SpaceType = 'phase' | 'building' | 'unit';
export interface HousingRecord {
  id: string;
  enabled: boolean;
  effective_enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface SpaceAncestor {
  id: string;
  node_type: SpaceType;
  name: string;
}
export interface SpaceNode extends HousingRecord, SpaceAncestor {
  community_id: string;
  parent_id: string | null;
  external_code: string | null;
  sort_order: number;
  has_children: boolean;
  ancestors: SpaceAncestor[];
}
export interface House extends HousingRecord {
  community_id: string;
  space_node_id: string;
  room_no: string;
  floor_no: number | null;
  external_code: string | null;
  display_address: string;
}
export interface HouseOwner extends HousingRecord {
  house_id: string;
  name: string;
  phone: string;
}
export interface OwnerInput {
  name: string;
  phone: string;
}
export interface SpaceInput {
  parent_id?: string | null;
  node_type: SpaceType;
  name: string;
  external_code?: string | null;
  sort_order?: number;
}
export interface HouseInput {
  space_node_id: string;
  room_no: string;
  floor_no?: number | null;
  external_code?: string | null;
  owners?: OwnerInput[];
}
export type HouseUpdate = Partial<
  Pick<House, 'room_no' | 'floor_no' | 'external_code' | 'enabled'>
>;
export type SpaceUpdate = Partial<
  Pick<SpaceNode, 'name' | 'external_code' | 'sort_order' | 'enabled'>
>;
type Filters = Record<string, string | number | boolean | undefined>;

export function createHousingApi(request: AdminRequest) {
  const root = (communityId: string) =>
    `/v1/communities/${encodeURIComponent(communityId)}`;
  const nodes = (c: string) => `${root(c)}/space-nodes`;
  const houses = (c: string) => `${root(c)}/houses`;
  const house = (c: string, h: string) =>
    `${houses(c)}/${encodeURIComponent(h)}`;
  const owners = (c: string, h: string) => `${house(c, h)}/owners`;
  const write = createJsonWriter(request);
  return {
    nodes: (c: string, filters: Filters) =>
      request<Page<SpaceNode>>(`${nodes(c)}?${queryString(filters)}`),
    node: (c: string, id: string) =>
      request<SpaceNode>(`${nodes(c)}/${encodeURIComponent(id)}`),
    createNode: (c: string, data: SpaceInput) =>
      write<SpaceNode>(nodes(c), 'POST', data),
    updateNode: (c: string, id: string, data: SpaceUpdate) =>
      write<SpaceNode>(`${nodes(c)}/${encodeURIComponent(id)}`, 'PATCH', data),
    houses: (c: string, filters: Filters) =>
      request<Page<House>>(`${houses(c)}?${queryString(filters)}`),
    house: (c: string, id: string) => request<House>(house(c, id)),
    createHouse: (c: string, data: HouseInput) =>
      write<House>(houses(c), 'POST', data),
    updateHouse: (c: string, id: string, data: HouseUpdate) =>
      write<House>(house(c, id), 'PATCH', data),
    owners: (c: string, h: string, filters: Filters) =>
      request<Page<HouseOwner>>(`${owners(c, h)}?${queryString(filters)}`, {
        cache: 'no-store',
      }),
    owner: (c: string, h: string, id: string) =>
      request<HouseOwner>(`${owners(c, h)}/${encodeURIComponent(id)}`, {
        cache: 'no-store',
      }),
    createOwner: (c: string, h: string, data: OwnerInput) =>
      write<HouseOwner>(owners(c, h), 'POST', data),
    updateOwner: (
      c: string,
      h: string,
      id: string,
      data: Partial<OwnerInput> & { enabled?: boolean },
    ) =>
      write<HouseOwner>(
        `${owners(c, h)}/${encodeURIComponent(id)}`,
        'PATCH',
        data,
      ),
  };
}
