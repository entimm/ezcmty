import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript';

const root = new URL('../', import.meta.url);
const input = new URL('../openapi/openapi.yaml', import.meta.url);
const output = new URL('../openapi/types.d.ts', import.meta.url);
const require = createRequire(import.meta.url);

// openapi-typescript 7.13 ignores properties next to $ref. Express their
// OpenAPI 3.1 intersection as allOf, preserving both the base and refinement.
function preserveRefProperties(schema) {
  if (Array.isArray(schema)) return schema.map(preserveRefProperties);
  if (!schema || typeof schema !== 'object') return schema;
  const mapped = Object.fromEntries(
    Object.entries(schema).map(([key, value]) => [
      key,
      preserveRefProperties(value),
    ]),
  );
  if ('$ref' in mapped && 'properties' in mapped) {
    const { $ref, ...constraints } = mapped;
    return { allOf: [{ $ref }, constraints] };
  }
  return mapped;
}

const document = JSON.parse(
  execFileSync(
    process.execPath,
    [
      require.resolve('@redocly/cli/bin/cli.js'),
      'bundle',
      fileURLToPath(input),
      '--ext',
      'json',
    ],
    {
      cwd: root,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'inherit'],
      maxBuffer: 16 * 1024 * 1024,
      env: { ...process.env, REDOCLY_SUPPRESS_UPDATE_NOTICE: 'true' },
    },
  ),
);
document.components.schemas = Object.fromEntries(
  Object.entries(document.components.schemas).map(([name, schema]) => [
    name,
    preserveRefProperties(schema),
  ]),
);
const contents =
  COMMENT_HEADER +
  astToString(
    await openapiTS(document, {
      arrayLength: true,
      defaultNonNullable: false,
    }),
  );

const current = await readFile(output, 'utf8').catch((error) => {
  if (error.code === 'ENOENT') return null;
  throw error;
});
if (current === contents) {
  console.log('OpenAPI types are up to date');
} else {
  // Concurrent consumers must see a complete old or new declaration, never a
  // partially written file. Keep the unique staging directory on the same FS.
  const temporary = await mkdtemp(
    new URL('../openapi/.types-', import.meta.url),
  );
  try {
    const staged = join(temporary, 'types.d.ts');
    await writeFile(staged, contents);
    await rename(staged, output);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
  console.log('Generated openapi/types.d.ts');
}
