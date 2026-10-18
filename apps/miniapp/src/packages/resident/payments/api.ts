import { residentRequest } from '../../../auth/resident';
import { PageResult } from '../../../auth/types';
import { query } from '../../../shared/http/client';
import { ClientParameters, PaymentInput, PaymentOrder } from './types';
const root = '/miniapp-users/me/payment-orders';
const path = (id: string) => root + '/' + encodeURIComponent(id);
export const orders = (page = 1, status = '') =>
  residentRequest<PageResult<PaymentOrder>>(root + query({ page, status }));
export const order = (id: string) => residentRequest<PaymentOrder>(path(id));
export const createOrder = (data: PaymentInput, key: string) =>
  residentRequest<PaymentOrder>(root, { method: 'POST', data, key });
export const parameters = (id: string) =>
  residentRequest<ClientParameters>(path(id) + '/client-payment-parameters', {
    method: 'POST',
  });
export const refresh = (id: string) =>
  residentRequest<PaymentOrder>(path(id) + '/refreshes', { method: 'POST' });
export const close = (id: string) =>
  residentRequest<PaymentOrder>(path(id) + '/closures', { method: 'POST' });
