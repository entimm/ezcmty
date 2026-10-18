import { residentRequest } from '../../../auth/resident';
import { PageResult } from '../../../auth/types';
import { query } from '../../../shared/http/client';
import { ResidentBill, SettlementEntry } from './types';

const root = '/miniapp-users/me';
export const bills = (bindingId: string, page = 1, scope = 'outstanding') =>
  residentRequest<PageResult<ResidentBill>>(
    root +
      '/house-bindings/' +
      encodeURIComponent(bindingId) +
      '/bills' +
      query({ page, scope }),
  );
export const bill = (id: string) =>
  residentRequest<ResidentBill>(root + '/bills/' + encodeURIComponent(id));
export const entries = (id: string, page = 1) =>
  residentRequest<PageResult<SettlementEntry>>(
    root +
      '/bills/' +
      encodeURIComponent(id) +
      '/settlement-entries' +
      query({ page }),
  );
