import { writeFile } from 'node:fs/promises';
const base = (
  process.env.MINIAPP_API_BASE_URL || 'http://127.0.0.1:8003'
).replace(/\/$/, '');
const parsed = new URL(base);
if (
  !['http:', 'https:'].includes(parsed.protocol) ||
  parsed.search ||
  parsed.hash ||
  parsed.username ||
  parsed.password
)
  throw new Error('Invalid MINIAPP_API_BASE_URL');
const buildVersion = new Date(Date.now() + 8 * 60 * 60 * 1000)
  .toISOString()
  .replace(/\D/g, '')
  .slice(0, 14);
await writeFile(
  'dist/config.js',
  '"use strict";Object.defineProperty(exports,"__esModule",{value:true});exports.API_BASE_URL=' +
    JSON.stringify(base) +
    ';exports.BUILD_VERSION=' +
    JSON.stringify(buildVersion) +
    ';\n',
);
console.log('Mini-program build version: ' + buildVersion);
