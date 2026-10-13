import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';

await access('dist/app.js');
const app = JSON.parse(await readFile('dist/app.json', 'utf8'));
assert(Array.isArray(app.pages) && app.pages.length > 0);
for (const page of app.pages) {
  await access(`dist/${page}.js`);
  await access(`dist/${page}.wxml`);
}
console.log('Mini-program build files verified');
