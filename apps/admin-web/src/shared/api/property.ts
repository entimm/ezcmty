import type { Account } from './admin';

export interface PropertyCompany {
  id: string;
  code: string;
  name: string;
  contact_name: string | null;
  contact_phone: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface Community {
  id: string;
  property_company_id: string;
  property_company_name: string;
  code: string;
  name: string;
  address: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface PropertyAdmin extends Account {
  scope: 'property_admin';
  property_company_id: string;
}
export interface CompanyCreate {
  code: string;
  name: string;
  contact_name?: string | null;
  contact_phone?: string | null;
}
export interface CommunityCreate {
  code: string;
  name: string;
  address: string;
  property_company_id: string;
}
export interface PropertyAdminCreate {
  login_name: string;
  display_name: string;
  password: string;
}
