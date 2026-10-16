import { residentRequest } from '../../auth/resident';
import { PageResult } from '../../auth/types';
import { query } from '../../shared/http/client';
import {
  Binding,
  BindingStatus,
  Claim,
  ClaimInput,
  ClaimStatus,
  Community,
  House,
  SpaceNode,
} from './types';
const me = '/miniapp-users/me';
export const communities = (name = '', page = 1) =>
  residentRequest<PageResult<Community>>(
    '/claimable-communities' + query({ name, page }),
  );
export const nodes = (communityId: string, parentId?: string, page = 1) =>
  residentRequest<PageResult<SpaceNode>>(
    '/claimable-communities/' +
      communityId +
      '/space-nodes' +
      query({ parent_id: parentId, page }),
  );
export const houses = (
  communityId: string,
  spaceId: string,
  roomNo = '',
  page = 1,
) =>
  residentRequest<PageResult<House>>(
    '/claimable-communities/' +
      communityId +
      '/houses' +
      query({ space_node_id: spaceId, room_no: roomNo, page }),
  );
export const house = (communityId: string, houseId: string) =>
  residentRequest<House>(
    '/claimable-communities/' + communityId + '/houses/' + houseId,
  );
export const claims = (page = 1, status?: ClaimStatus) =>
  residentRequest<PageResult<Claim>>(
    me + '/house-claims' + query({ page, status }),
  );
export const claim = (id: string) =>
  residentRequest<Claim>(me + '/house-claims/' + id);
export const createClaim = (data: ClaimInput, key: string) =>
  residentRequest<Claim>(me + '/house-claims', { method: 'POST', data, key });
export const cancelClaim = (item: Claim) =>
  residentRequest<Claim>(me + '/house-claims/' + item.id + '/cancellations', {
    method: 'POST',
    data: { expected_row_version: item.row_version },
  });
export const bindings = (page = 1, status?: BindingStatus) =>
  residentRequest<PageResult<Binding>>(
    me + '/house-bindings' + query({ page, status }),
  );
export const binding = (id: string) =>
  residentRequest<Binding>(me + '/house-bindings/' + id);
export const releaseBinding = (item: Binding) =>
  residentRequest<Binding>(me + '/house-bindings/' + item.id + '/releases', {
    method: 'POST',
    data: { expected_row_version: item.row_version },
  });
