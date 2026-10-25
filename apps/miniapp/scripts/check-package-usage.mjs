import path from 'node:path';
import ts from 'typescript';

// Inspect emitted CommonJS: erased type imports cannot count as runtime use.
export function subpackageOnlyModules(contents, app) {
  const groups = app.subpackages || app.subPackages || [];
  const graph = new Map();
  const resolve = (origin, reference, suffixes) => {
    const base = reference.startsWith('/')
      ? reference.slice(1)
      : path.posix.join(path.posix.dirname(origin), reference);
    return suffixes
      .map((suffix) => base + suffix)
      .find((file) => contents.has(file));
  };
  for (const [file, content] of contents) {
    if (!file.endsWith('.js')) continue;
    const dependencies = new Set();
    graph.set(file, dependencies);
    const source = ts.createSourceFile(
      file,
      content,
      ts.ScriptTarget.ESNext,
      true,
      ts.ScriptKind.JS,
    );
    const inspect = (node) => {
      if (
        ts.isCallExpression(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === 'require' &&
        node.arguments.length === 1 &&
        ts.isStringLiteral(node.arguments[0]) &&
        node.arguments[0].text.startsWith('.')
      ) {
        const target = resolve(file, node.arguments[0].text, [
          '',
          '.js',
          '/index.js',
        ]);
        if (target) dependencies.add(target);
      }
      ts.forEachChild(node, inspect);
    };
    inspect(source);
    const config = JSON.parse(
      contents.get(file.slice(0, -3) + '.json') || '{}',
    );
    for (const reference of Object.values(config.usingComponents || {})) {
      const target = resolve(file, reference, ['.js']);
      if (target) dependencies.add(target);
    }
  }
  const reachable = (roots) => {
    const seen = new Set();
    const pending = [...roots];
    while (pending.length) {
      const file = pending.pop();
      if (seen.has(file)) continue;
      seen.add(file);
      pending.push(...(graph.get(file) || []));
    }
    return seen;
  };
  const main = reachable(['app.js', ...app.pages.map((page) => page + '.js')]);
  const subpackages = groups.map((group) =>
    reachable(group.pages.map((page) => group.root + '/' + page + '.js')),
  );
  return [...graph.keys()]
    .filter(
      (file) =>
        !groups.some((group) => file.startsWith(group.root + '/')) &&
        !main.has(file) &&
        subpackages.filter((used) => used.has(file)).length === 1,
    )
    .sort();
}
