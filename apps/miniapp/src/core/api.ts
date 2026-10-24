import { query } from './request';
import { residentRequest } from './session';
import {
  Binding,
  BindingStatus,
  Claim,
  ClaimInput,
  ClaimStatus,
  ClientParameters,
  Community,
  ConfirmationStatus,
  House,
  PageResult,
  PaymentInput,
  PaymentOrder,
  PaymentStatus,
  PhoneBinding,
  ResidentBill,
  SettlementEntry,
  SpaceNode,
  User,
} from './types';

const me = '/miniapp-users/me';
const id = encodeURIComponent;
export const user = () => residentRequest<User>(me);
export const listPhones = (page = 1) =>
  residentRequest<PageResult<PhoneBinding>>(
    me + '/phone-bindings' + query({ page, page_size: 100 }),
  );
export const bindPhone = (code: string, key: string, expectedPhone?: string) =>
  residentRequest<PhoneBinding>(me + '/phone-bindings', {
    method: 'POST',
    key,
    data: { code, ...(expectedPhone ? { expected_phone: expectedPhone } : {}) },
  });
export const unbindPhone = (phone: PhoneBinding) =>
  residentRequest<void>(
    me +
      '/phone-bindings/' +
      id(phone.id) +
      query({ expected_row_version: phone.row_version }),
    { method: 'DELETE' },
  );
export const communities = (name = '', page = 1) =>
  residentRequest<PageResult<Community>>(
    '/claimable-communities' + query({ name, page }),
  );
export const nodes = (communityId: string, parentId?: string, page = 1) =>
  residentRequest<PageResult<SpaceNode>>(
    '/claimable-communities/' +
      id(communityId) +
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
      id(communityId) +
      '/houses' +
      query({ space_node_id: spaceId, room_no: roomNo, page }),
  );
export const house = (communityId: string, houseId: string) =>
  residentRequest<House>(
    '/claimable-communities/' + id(communityId) + '/houses/' + id(houseId),
  );
export const claims = (page = 1, status?: ClaimStatus) =>
  residentRequest<PageResult<Claim>>(
    me + '/house-claims' + query({ page, status }),
  );
export const claim = (claimId: string) =>
  residentRequest<Claim>(me + '/house-claims/' + id(claimId));
export const createClaim = (data: ClaimInput, key: string) =>
  residentRequest<Claim>(me + '/house-claims', { method: 'POST', data, key });
export const cancelClaim = (item: Claim) =>
  residentRequest<Claim>(
    me + '/house-claims/' + id(item.id) + '/cancellations',
    { method: 'POST', data: { expected_row_version: item.row_version } },
  );
export const bindings = (page = 1, status?: BindingStatus) =>
  residentRequest<PageResult<Binding>>(
    me + '/house-bindings' + query({ page, status }),
  );
export const binding = (bindingId: string) =>
  residentRequest<Binding>(me + '/house-bindings/' + id(bindingId));
export const releaseBinding = (item: Binding) =>
  residentRequest<Binding>(
    me + '/house-bindings/' + id(item.id) + '/releases',
    { method: 'POST', data: { expected_row_version: item.row_version } },
  );

export interface BillFilters {
  billing_month_from?: string;
  billing_month_to?: string;
  page_size?: number;
  sort?: '-billing_month,-id' | 'billing_month,id';
}
export const bills = (
  bindingId: string,
  page = 1,
  scope: 'outstanding' | 'all' = 'outstanding',
  filters: BillFilters = {},
) =>
  residentRequest<PageResult<ResidentBill>>(
    me +
      '/house-bindings/' +
      id(bindingId) +
      '/bills' +
      query({ page, scope, ...filters }),
  );
export const bill = (billId: string) =>
  residentRequest<ResidentBill>(me + '/bills/' + id(billId));
export const entries = (billId: string, page = 1) =>
  residentRequest<PageResult<SettlementEntry>>(
    me + '/bills/' + id(billId) + '/settlement-entries' + query({ page }),
  );

export interface OrderFilters {
  confirmation_status?: ConfirmationStatus;
  idempotency_key?: string;
  created_at_from?: string;
  created_at_to?: string;
  page_size?: number;
  sort?: '-created_at,-id' | 'created_at,id';
}
const orderPath = (orderId: string) => me + '/payment-orders/' + id(orderId);
export const orders = (
  page = 1,
  status: PaymentStatus | '' = '',
  filters: OrderFilters = {},
) =>
  residentRequest<PageResult<PaymentOrder>>(
    me + '/payment-orders' + query({ page, status, ...filters }),
  );
export const order = (orderId: string) =>
  residentRequest<PaymentOrder>(orderPath(orderId));
export const createOrder = (data: PaymentInput, key: string) =>
  residentRequest<PaymentOrder>(me + '/payment-orders', {
    method: 'POST',
    data,
    key,
  });
export const parameters = (orderId: string) =>
  residentRequest<ClientParameters>(
    orderPath(orderId) + '/client-payment-parameters',
    { method: 'POST' },
  );
export const refresh = (orderId: string) =>
  residentRequest<PaymentOrder>(orderPath(orderId) + '/refreshes', {
    method: 'POST',
  });
export const close = (orderId: string) =>
  residentRequest<PaymentOrder>(orderPath(orderId) + '/closures', {
    method: 'POST',
  });
