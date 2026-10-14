import { RuleTester } from 'eslint';
import { resolve } from 'node:path';
import { describe, it } from 'vitest';
import { createAdminBoundaryRule } from './module-boundaries.mjs';

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const sourceRoot = resolve('test-project/src');
const filename = (path) => resolve(sourceRoot, path);

new RuleTester().run(
  'admin module boundaries',
  createAdminBoundaryRule(sourceRoot),
  {
    valid: [
      {
        filename: filename('features/platform/accounts/Editor.ts'),
        code: "import { api } from '../property/api';",
      },
      {
        filename: filename('components/Search.ts'),
        code: "import { state } from '@/auth/use-admin-session';",
      },
      {
        filename: filename('app/platform/App.ts'),
        code: "import { provider } from '../AdminAppProvider';",
      },
      {
        filename: filename('app/admin-routes.ts'),
        code: "import { config } from './property/config';",
      },
    ],
    invalid: [
      {
        filename: filename('features/property/api.ts'),
        code: "import { api } from '@/features/platform/api';",
        errors: [{ messageId: 'foreign' }],
      },
      {
        filename: filename('features/platform/property/Editor.ts'),
        code: "export * from '../../property/api';",
        errors: [{ messageId: 'foreign' }],
      },
      {
        filename: filename('app/property/App.ts'),
        code: "export { config } from '../platform/config';",
        errors: [{ messageId: 'foreign' }],
      },
      {
        filename: filename('shared/client.ts'),
        code: "const api = await import('@/features/platform/api');",
        errors: [{ messageId: 'common' }],
      },
      {
        filename: filename('components/Search.ts'),
        code: "import { picker } from '../features/platform/property/CompanyPicker';",
        errors: [{ messageId: 'common' }],
      },
      {
        filename: filename('features/profile/Page.ts'),
        code: "import { routes } from '../../app/admin-routes';",
        errors: [{ messageId: 'common' }],
      },
      {
        filename: filename('features/platform/Home.ts'),
        code: "import { routes } from '../../app/admin-routes';",
        errors: [{ messageId: 'assembly' }],
      },
      {
        filename: filename('app/property/App.ts'),
        code: "const config = require('../admin-routes');",
        errors: [{ messageId: 'assembly' }],
      },
    ],
  },
);
