export const appName = process.env.UMI_APP_NAME || '社区物业平台';

export const adminApiBases = {
  platform_admin: process.env.UMI_APP_PLATFORM_API_BASE || '/api/platform',
  property_admin: process.env.UMI_APP_PROPERTY_API_BASE || '/api/property',
};
