import { useContext } from 'react';

import { AdminSessionContext } from './session-context';

export function useAdminSession() {
  const context = useContext(AdminSessionContext);
  if (!context) {
    throw new Error('Admin session requires an application provider');
  }
  return context;
}
