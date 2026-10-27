import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import { checkTypeScriptModule } from '../../scripts/check-boundaries.mjs';

const origin = fileURLToPath(
  new URL('../../src/core/types.ts', import.meta.url),
);
const contract = '../../../../openapi/types';

it.each([
  'import type { components } from "$contract";',
  'import type * as contract from "$contract";',
  'import { type components, type operations } from "$contract";',
  'export type { components } from "$contract";',
  'export { type components, type operations } from "$contract";',
  'export type * from "$contract";',
  'import type { components } from "$contract.d.ts";',
  'type Schema = import("$contract").components;',
])('allows erased contract references: %s', async (content) => {
  await expect(
    checkTypeScriptModule(origin, content.replace('$contract', contract)),
  ).resolves.toBeUndefined();
});

it.each([
  'import { components } from "$contract";',
  'import { type components, runtime } from "$contract";',
  'import runtime, { type components } from "$contract";',
  'import * as contract from "$contract";',
  'import "$contract";',
  'export { components } from "$contract";',
  'export { type components, runtime } from "$contract";',
  'export * from "$contract";',
  'const contract = require("$contract");',
  'import contract = require("$contract");',
])('rejects runtime contract references: %s', async (content) => {
  await expect(
    checkTypeScriptModule(origin, content.replace('$contract', contract)),
  ).rejects.toThrow('Reference escapes miniapp');
});

it('keeps dynamic imports unsupported even for the generated declarations', async () => {
  await expect(
    checkTypeScriptModule(origin, `const contract = import("${contract}");`),
  ).rejects.toThrow('Dynamic import unsupported');
});

it('does not allow other files outside the miniapp through type-only imports', async () => {
  await expect(
    checkTypeScriptModule(
      origin,
      'import type { components } from "../../../../openapi/other-types";',
    ),
  ).rejects.toThrow('Reference escapes miniapp');
  await expect(
    checkTypeScriptModule(
      origin,
      'type Schema = import("../../../../openapi/other-types").components;',
    ),
  ).rejects.toThrow('Reference escapes miniapp');
});

it('keeps main-package and subpackage type boundaries enforced', async () => {
  await expect(
    checkTypeScriptModule(
      origin,
      'import type { ClaimSubmission } from "../packages/resident/claims";',
    ),
  ).rejects.toThrow('Main/subpackage boundary');
  await expect(
    checkTypeScriptModule(
      path.resolve(path.dirname(origin), '../packages/other/page.ts'),
      'import type { ClaimSubmission } from "../resident/claims";',
    ),
  ).rejects.toThrow('Main/subpackage boundary');
});
