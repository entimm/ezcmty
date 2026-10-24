import assert from 'node:assert/strict';
import { access, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const sourceRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../src',
);
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
function boundary(origin, target) {
  const from = path.relative(sourceRoot, origin).split(path.sep);
  const to = path.relative(sourceRoot, target).split(path.sep);
  assert(
    to[0] !== '..' && !path.isAbsolute(to.join('/')),
    `Reference escapes miniapp: ${origin}`,
  );
  if (to[0] === 'packages')
    assert(
      from[0] === 'packages' && from[1] === to[1],
      `Main/subpackage boundary: ${origin} -> ${target}`,
    );
}
async function moduleExists(destination) {
  for (const candidate of [
    destination,
    destination + '.ts',
    path.join(destination, 'index.ts'),
  ]) {
    try {
      await access(candidate);
      return;
    } catch {
      /* Try normal native TS resolution. */
    }
  }
  assert.fail(`Runtime module missing: ${destination}`);
}

for (const file of await files(sourceRoot)) {
  if (file.endsWith('.ts')) {
    const source = ts.createSourceFile(
      file,
      await readFile(file, 'utf8'),
      ts.ScriptTarget.ESNext,
      true,
    );
    const specifiers = [];
    const inspect = (node) => {
      if (
        (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
        node.moduleSpecifier
      ) {
        assert(
          ts.isStringLiteral(node.moduleSpecifier),
          `Computed import unsupported: ${file}`,
        );
        specifiers.push(node.moduleSpecifier.text);
      }
      if (
        ts.isCallExpression(node) &&
        (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
          node.expression.getText(source) === 'require')
      ) {
        assert(
          node.expression.kind !== ts.SyntaxKind.ImportKeyword,
          `Dynamic import unsupported in native miniapp: ${file}`,
        );
        assert(
          node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0]),
          `Computed require unsupported: ${file}`,
        );
        specifiers.push(node.arguments[0].text);
      }
      ts.forEachChild(node, inspect);
    };
    inspect(source);
    for (const specifier of specifiers) {
      assert(
        specifier.startsWith('.'),
        `Native runtime import must be relative: ${file} -> ${specifier}`,
      );
      const destination = path.resolve(path.dirname(file), specifier);
      boundary(file, destination);
      await moduleExists(destination);
    }
  }
  if (file.endsWith('.json')) {
    const config = JSON.parse(await readFile(file, 'utf8'));
    for (const reference of Object.values(config.usingComponents || {})) {
      assert(
        typeof reference === 'string' && !reference.includes('://'),
        `External component unsupported: ${file}`,
      );
      const destination = reference.startsWith('/')
        ? path.join(sourceRoot, reference)
        : path.resolve(path.dirname(file), reference);
      boundary(file, destination);
      for (const suffix of ['ts', 'json', 'wxml', 'wxss'])
        await access(destination + '.' + suffix);
      const component = JSON.parse(
        await readFile(destination + '.json', 'utf8'),
      );
      assert(
        component.component === true,
        `Component flag missing: ${destination}`,
      );
    }
  }
  if (file.endsWith('.wxml') || file.endsWith('.wxss')) {
    const source = await readFile(file, 'utf8');
    const references = file.endsWith('.wxml')
      ? [...source.matchAll(/<(?:import|include)\s+src=["']([^"']+)["']/g)].map(
          (match) => match[1],
        )
      : [...source.matchAll(/@import\s+["']([^"']+)["']/g)].map(
          (match) => match[1],
        );
    for (const reference of references) {
      const destination = reference.startsWith('/')
        ? path.join(sourceRoot, reference)
        : path.resolve(path.dirname(file), reference);
      boundary(file, destination);
      await access(destination);
    }
  }
}
console.log('Miniapp native module and component boundaries verified');
