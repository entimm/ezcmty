import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';
import './check-boundaries.mjs';
await access('dist/app.js');
const app = JSON.parse(await readFile('dist/app.json', 'utf8'));
assert(Array.isArray(app.pages) && app.pages.length > 0);
const pages = [
  ...app.pages,
  ...(app.subPackages || []).flatMap((group) =>
    group.pages.map((page) => group.root + '/' + page),
  ),
];
assert(new Set(pages).size === pages.length);
for (const page of pages)
  for (const suffix of ['js', 'json', 'wxml', 'wxss'])
    await access(`dist/${page}.${suffix}`);
assert(!app.tabBar, 'Business navigation belongs inside its package');
console.log(`Mini-program build verified: ${pages.length} pages`);
