import { query } from './request';
import { clientRequest } from './session';
import type {
  ClientIdentity,
  ClientIdentityPage,
  PageResult,
  PhoneBinding,
  User,
} from './types';

const me = '/miniapp-users/me';
const id = encodeURIComponent;
export const user = () => clientRequest<User>(me);
export const listPhones = (page = 1) =>
  clientRequest<PageResult<PhoneBinding>>(
    me + '/phone-bindings' + query({ page, page_size: 100 }),
  );
export const bindPhone = (code: string, key: string, expectedPhone?: string) =>
  clientRequest<PhoneBinding>(me + '/phone-bindings', {
    method: 'POST',
    key,
    data: { code, ...(expectedPhone ? { expected_phone: expectedPhone } : {}) },
  });
export const unbindPhone = (phone: PhoneBinding) =>
  clientRequest<void>(
    me +
      '/phone-bindings/' +
      id(phone.id) +
      query({ expected_row_version: phone.row_version }),
    { method: 'DELETE' },
  );
export const identities = (page = 1) =>
  clientRequest<ClientIdentityPage>(
    me + '/identities' + query({ page, page_size: 100 }),
  );
export const identity = (identityId: string) =>
  clientRequest<ClientIdentity>(me + '/identities/' + id(identityId));
