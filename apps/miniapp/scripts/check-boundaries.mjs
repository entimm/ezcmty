import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve('src');
async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  return (
    await Promise.all(
      entries.map((entry) =>
        entry.isDirectory()
          ? walk(path.join(directory, entry.name))
          : [path.join(directory, entry.name)],
      ),
    )
  ).flat();
}
for (const file of await walk(root)) {
  if (!file.endsWith('.ts')) continue;
  const source = await readFile(file, 'utf8');
  const origin = path.relative(root, file).split(path.sep);
  const imports = source.matchAll(
    /(?:from\s*|import\s*\(?\s*|require\s*\(\s*)['"]([^'"]+)['"]/g,
  );
  for (const [, specifier] of imports) {
    assert(
      specifier.startsWith('.'),
      `Native runtime import must be relative: ${file}`,
    );
    const destination = path
      .relative(root, path.resolve(path.dirname(file), specifier))
      .split(path.sep);
    assert(destination[0] !== '..', `Import outside miniapp: ${file}`);
    if (destination[0] === 'packages')
      assert(
        origin[0] === 'packages' && origin[1] === destination[1],
        `Business package boundary: ${file}`,
      );
    if (origin[0] === 'shared')
      assert(
        !['auth', 'packages', 'pages'].includes(destination[0]),
        `Shared layer depends on business/session: ${file}`,
      );
  }
}
console.log('Mini-program import boundaries verified');
