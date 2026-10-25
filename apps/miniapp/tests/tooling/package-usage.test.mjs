import { expect, it } from 'vitest';
import ts from 'typescript';
import { subpackageOnlyModules } from '../../scripts/check-package-usage.mjs';

const app = {
  pages: ['pages/index'],
  subpackages: [{ root: 'packages/resident', pages: ['pages/home'] }],
};
const analyze = (files, config = app) =>
  subpackageOnlyModules(new Map(Object.entries(files)), config);

it('reports main-package modules used only by one subpackage, including transitive dependencies', () => {
  expect(
    analyze({
      'app.js': 'App({});',
      'pages/index.js': 'Page({});',
      'packages/resident/pages/home.js': 'require("../../../core/claims");',
      'core/claims.js': 'require("./ids"); exports.claim = () => {};',
      'core/ids.js': 'exports.newKey = () => "key";',
      'core/unused.js': 'exports.value = 1;',
    }),
  ).toEqual(['core/claims.js', 'core/ids.js']);
});

it('retains modules reached transitively from the App, main pages, and component entries', () => {
  expect(
    analyze({
      'app.js': 'require("./core/startup"); App({});',
      'core/startup.js': 'require("./shared");',
      'app.json': JSON.stringify({
        usingComponents: { global: '/components/global' },
      }),
      'pages/index.js': 'require("../core/page"); Page({});',
      'pages/index.json': JSON.stringify({
        usingComponents: { local: '../components/local' },
      }),
      'components/local.js': 'require("../core/component"); Component({});',
      'components/global.js': 'require("../core/global"); Component({});',
      'core/shared.js': 'exports.value = 1;',
      'core/page.js': 'exports.value = 2;',
      'core/component.js': 'exports.value = 3;',
      'core/global.js': 'exports.value = 4;',
      'packages/resident/pages/home.js':
        'require("../../../core/shared"); require("../../../core/page");' +
        'require("../../../core/component"); require("../../../core/global");',
    }),
  ).toEqual([]);
});

it('follows subpackage components and resolves index modules and cycles', () => {
  expect(
    analyze({
      'pages/index.js': 'Page({});',
      'packages/resident/pages/home.js': 'Page({});',
      'packages/resident/pages/home.json': JSON.stringify({
        usingComponents: { card: '../components/card' },
      }),
      'packages/resident/components/card.js':
        'require("../../../core/payment"); Component({});',
      'core/payment/index.js':
        'require("../helper.js"); exports.pay = () => {};',
      'core/helper.js': 'require("./payment"); exports.value = 1;',
    }),
  ).toEqual(['core/helper.js', 'core/payment/index.js']);
});

it('retains main-package capabilities actually shared by multiple subpackages', () => {
  expect(
    analyze(
      {
        'packages/resident/pages/home.js': 'require("../../../core/shared");',
        'packages/property/pages/home.js': 'require("../../../core/shared");',
        'core/shared.js': 'require("./helper"); exports.value = 1;',
        'core/helper.js': 'exports.value = 2;',
      },
      {
        pages: app.pages,
        subPackages: [
          ...app.subpackages,
          { root: 'packages/property', pages: ['pages/home'] },
        ],
      },
    ),
  ).toEqual([]);
});

it('does not count erased type imports as main-package or subpackage runtime use', () => {
  const sources = {
    'pages/index.js':
      'import type { Claim } from "../core/claims"; const value: Claim | null = null;',
    'packages/resident/pages/home.js':
      'import { claim } from "../../../core/claims"; import type { Value } from "../../../core/types"; claim();',
    'core/claims.js':
      'export interface Claim {} export const claim = () => {};',
    'core/types.js': 'export interface Value {}',
  };
  const compiled = Object.fromEntries(
    Object.entries(sources).map(([file, source]) => [
      file,
      ts.transpileModule(source, {
        compilerOptions: { module: ts.ModuleKind.CommonJS },
      }).outputText,
    ]),
  );
  expect(analyze(compiled)).toEqual(['core/claims.js']);
});

it('ignores require-like text in comments and strings', () => {
  expect(
    analyze({
      'pages/index.js':
        '// require("../core/claims");\nconst example = `require("../core/claims")`;',
      'packages/resident/pages/home.js': 'require("../../../core/claims");',
      'core/claims.js': 'exports.claim = () => {};',
    }),
  ).toEqual(['core/claims.js']);
});
