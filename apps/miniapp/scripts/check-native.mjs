import { execFileSync } from 'node:child_process';
import { mkdir, readdir, access } from 'node:fs/promises';
import path from 'node:path';
const installed =
  '/Applications/wechatwebdevtools.app/Contents/Resources/app.asar.unpacked/node_modules/wcc-exec';
async function walk(dir) {
  return (
    await Promise.all(
      (await readdir(dir, { withFileTypes: true })).map((entry) =>
        entry.isDirectory()
          ? walk(path.join(dir, entry.name))
          : [path.join(dir, entry.name)],
      ),
    )
  ).flat();
}
await mkdir('.tmp', { recursive: true });
const files = await walk('dist');
for (const [extension, tool, setting] of [
  ['wxml', 'wcc', 'MINIAPP_WCC'],
  ['wxss', 'wcsc', 'MINIAPP_WCSC'],
]) {
  const compiler = process.env[setting] || path.join(installed, tool);
  await access(compiler);
  execFileSync(
    compiler,
    [
      '-o',
      path.resolve('.tmp/native-' + extension + '.js'),
      ...files
        .filter((file) => file.endsWith('.' + extension))
        .map((file) => path.relative('dist', file)),
    ],
    { cwd: 'dist', stdio: 'pipe' },
  );
}
console.log('WeChat native WXML and WXSS compilers passed');
