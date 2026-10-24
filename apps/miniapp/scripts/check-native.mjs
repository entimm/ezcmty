import { execFileSync } from 'node:child_process';
import { access, mkdir, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'dist');
const temporary = path.join(root, '.tmp');
const installed =
  '/Applications/wechatwebdevtools.app/Contents/Resources/app.asar.unpacked/node_modules/wcc-exec';
execFileSync(process.execPath, [path.join(root, 'scripts/build.mjs')], {
  cwd: root,
  stdio: 'inherit',
});
await mkdir(temporary, { recursive: true });
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
const built = await files(output);
for (const [extension, binary, environment] of [
  ['wxml', 'wcc', 'MINIAPP_WCC'],
  ['wxss', 'wcsc', 'MINIAPP_WCSC'],
]) {
  const compiler = process.env[environment] || path.join(installed, binary);
  await access(compiler);
  const inputs = built
    .filter((file) => file.endsWith('.' + extension))
    .map((file) => path.relative(output, file));
  if (!inputs.length)
    throw new Error('No native inputs collected for ' + extension);
  try {
    execFileSync(
      compiler,
      ['-o', path.join(temporary, 'native-' + extension + '.js'), ...inputs],
      { cwd: output, stdio: 'pipe', maxBuffer: 16 * 1024 * 1024 },
    );
  } catch (error) {
    console.error(
      `WeChat ${binary} compilation failed:\n` +
        (error.stderr?.toString() || error.message),
    );
    process.exit(1);
  }
  console.log(`WeChat ${binary} verified ${inputs.length} ${extension} files`);
}
