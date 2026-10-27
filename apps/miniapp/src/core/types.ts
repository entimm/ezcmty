import type { components } from '../../../../openapi/types';

type Schemas = components['schemas'];

export type User = Schemas['MiniappUser'];
export type ClientSession = Schemas['ClientSession'];
export type ClientSessionState = Schemas['ClientSessionState'];
export type PageResult<T> = Omit<Schemas['PhoneBindingPage'], 'items'> & {
  items: T[];
};
export type PhoneBinding = Schemas['PhoneBinding'];
export type ClientIdentity = Schemas['ClientIdentity'];
export type ClientIdentityPage = Schemas['ClientIdentityPage'];
