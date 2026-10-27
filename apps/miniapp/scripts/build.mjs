import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import {
  access,
  copyFile,
  mkdir,
  readFile,
  readdir,
  rm,
  stat,
  writeFile,
} from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { subpackageOnlyModules } from './check-package-usage.mjs';

await import('../../../scripts/generate_api_types.mjs');
await import('./check-boundaries.mjs');

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = path.join(root, 'src');
const output = path.join(root, 'dist');
const require = createRequire(import.meta.url);
async function files(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  return (
    await Promise.all(
      entries.map((entry) =>
        entry.isDirectory()
          ? files(path.join(directory, entry.name))
          : [path.join(directory, entry.name)],
      ),
    )
  ).flat();
}

const sourceConfig = await readFile(path.join(source, 'config.ts'), 'utf8');
const defaultBase = sourceConfig.match(
  /export const API_BASE_URL\s*=\s*['"]([^'"]+)['"]/,
)?.[1];
assert(defaultBase, 'API_BASE_URL must have a development default');
const rawBase = process.env.MINIAPP_API_BASE_URL || defaultBase;
const base = new URL(rawBase);
assert(
  ['http:', 'https:'].includes(base.protocol),
  'MINIAPP_API_BASE_URL must use HTTP or HTTPS',
);
assert(
  !base.username && !base.password && !base.search && !base.hash,
  'API URL must not contain credentials, query, or fragment',
);
assert(base.hostname, 'API hostname is required');
if (process.env.NODE_ENV === 'production')
  assert(base.protocol === 'https:', 'Production API must use HTTPS');
const apiBase = base.href.replace(/\/$/, '');
const migrations = JSON.parse(
  process.env.MINIAPP_API_STORAGE_MIGRATIONS || '[]',
);
assert(
  Array.isArray(migrations),
  'Storage migrations must be an explicit JSON array',
);
for (const item of migrations) {
  assert(
    item && Object.keys(item).sort().join(',') === 'from,to',
    'Each migration requires only from/to',
  );
  for (const value of [item.from, item.to]) {
    assert(typeof value === 'string', 'Migration URLs must be strings');
    const url = new URL(value);
    assert(
      ['http:', 'https:'].includes(url.protocol) &&
        !url.username &&
        !url.password &&
        !url.search &&
        !url.hash &&
        url.href.replace(/\/$/, '') === value,
      'Migration URLs must be canonical absolute API bases',
    );
    if (process.env.NODE_ENV === 'production')
      assert(
        url.protocol === 'https:',
        'Production migration URLs must use HTTPS',
      );
  }
  assert(
    item.to === apiBase && item.from !== item.to,
    'Migration target must match this deployment API base',
  );
}
const version =
  process.env.MINIAPP_BUILD_VERSION ||
  process.env.BUILD_VERSION ||
  new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
    .format(new Date())
    .replace(/\D/g, '');
assert(
  /^[A-Za-z0-9._-]{1,80}$/.test(version),
  'Build version must be a safe 1–80 character identifier',
);

// Every build starts from source; a stale JS or deleted page can never survive.
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
execFileSync(
  process.execPath,
  [
    require.resolve('typescript/bin/tsc'),
    '--project',
    path.join(root, 'tsconfig.json'),
  ],
  { cwd: root, stdio: 'inherit' },
);
const staticExtensions = new Set([
  '.wxml',
  '.wxss',
  '.json',
  '.svg',
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  '.gif',
]);
for (const file of await files(source)) {
  if (!staticExtensions.has(path.extname(file))) continue;
  const destination = path.join(output, path.relative(source, file));
  await mkdir(path.dirname(destination), { recursive: true });
  await copyFile(file, destination);
}
const compiledConfig = path.join(output, 'config.js');
const config = await readFile(compiledConfig, 'utf8');
assert(
  /exports\.API_BASE_URL\s*=\s*[^;]+;/.test(config),
  'Compiled API config missing',
);
assert(
  /exports\.BUILD_VERSION\s*=\s*[^;]+;/.test(config),
  'Compiled build version missing',
);
await writeFile(
  compiledConfig,
  config +
    '\nexports.API_STORAGE_MIGRATIONS = ' +
    JSON.stringify(migrations) +
    ';\nexports.API_BASE_URL = ' +
    JSON.stringify(apiBase) +
    ';\nexports.BUILD_VERSION = ' +
    JSON.stringify(version) +
    ';\n',
);

const app = JSON.parse(await readFile(path.join(output, 'app.json'), 'utf8'));
assert(!(app.subpackages && app.subPackages), 'Use one subpackages spelling');
const packages = app.subpackages || app.subPackages || [];
const pages = [
  ...app.pages,
  ...packages.flatMap((group) =>
    group.pages.map((page) => group.root + '/' + page),
  ),
];
assert(
  pages.length > 0 && new Set(pages).size === pages.length,
  'Registered routes must be unique',
);
await access(path.join(output, 'app.js'));
await access(path.join(output, 'app.wxss'));
for (const page of pages) {
  assert(
    !page.includes('..') && !page.startsWith('/'),
    'Page paths must stay in the miniapp',
  );
  for (const suffix of ['js', 'json', 'wxml', 'wxss'])
    await access(path.join(output, page + '.' + suffix));
}
const outputFiles = await files(output);
for (const file of outputFiles) {
  if (!file.endsWith('.json')) continue;
  const config = JSON.parse(await readFile(file, 'utf8'));
  for (const reference of Object.values(config.usingComponents || {})) {
    const destination = reference.startsWith('/')
      ? path.join(output, reference)
      : path.resolve(path.dirname(file), reference);
    for (const suffix of ['js', 'json', 'wxml', 'wxss'])
      await access(destination + '.' + suffix);
  }
}

const runtimeContents = new Map(
  await Promise.all(
    outputFiles
      .filter((file) => ['.js', '.json'].includes(path.extname(file)))
      .map(async (file) => [
        path.relative(output, file).split(path.sep).join('/'),
        await readFile(file, 'utf8'),
      ]),
  ),
);
const misplaced = subpackageOnlyModules(runtimeContents, app);
assert(
  misplaced.length === 0,
  `Main-package JS used only by one subpackage:\n${misplaced.join('\n')}`,
);

const iconNames = new Set(['circle-help']);
for (const file of await files(source)) {
  if (file.endsWith('.wxml')) {
    const source = await readFile(file, 'utf8');
    for (const [, value] of source.matchAll(
      /<(?:ui-icon\b[^>]*\bname|state-view\b[^>]*\bicon)="([^"]+)"/g,
    )) {
      if (/^[a-z0-9-]+$/.test(value)) iconNames.add(value);
      else
        for (const [, icon] of value.matchAll(/'([a-z0-9-]+)'/g))
          iconNames.add(icon);
    }
  }
  if (file.endsWith('.ts')) {
    const source = await readFile(file, 'utf8');
    for (const [, icon] of source.matchAll(
      /\bicon\s*[:=]\s*['"]([a-z0-9-]+)['"]/g,
    ))
      if (!['none', 'success', 'error', 'loading'].includes(icon))
        iconNames.add(icon);
    for (const [, object] of source.matchAll(/\bicon\s*:\s*\{([^}]+)\}/g))
      for (const [, icon] of object.matchAll(/:\s*['"]([a-z0-9-]+)['"]/g))
        iconNames.add(icon);
  }
}
for (const icon of iconNames)
  for (const tone of ['', '-green', '-blue', '-orange', '-muted'])
    await access(path.join(output, 'assets/icons', icon + tone + '.svg'));

const sizes = new Map([
  ['main', 0],
  ...packages.map((group) => [group.root, 0]),
]);
for (const file of outputFiles) {
  const relative = path.relative(output, file).split(path.sep).join('/');
  const scope =
    packages.find((group) => relative.startsWith(group.root + '/'))?.root ||
    'main';
  sizes.set(scope, sizes.get(scope) + (await stat(file)).size);
}
// Conservative engineering budgets; keep ample headroom for native packaging.
for (const [scope, bytes] of sizes)
  assert(bytes < 2 * 1024 * 1024, `${scope} exceeds the 2 MiB build budget`);
const total = [...sizes.values()].reduce((sum, bytes) => sum + bytes, 0);
assert(
  total < 20 * 1024 * 1024,
  'Miniapp exceeds the 20 MiB total build budget',
);
console.log(
  `Miniapp build verified: ${pages.length} pages; ` +
    [...sizes]
      .map(([scope, bytes]) => `${scope} ${(bytes / 1024).toFixed(1)} KiB`)
      .join('; ') +
    `; total ${(total / 1024).toFixed(1)} KiB; version ${version}`,
);
