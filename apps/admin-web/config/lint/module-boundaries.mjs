import { dirname, relative, resolve, sep } from 'node:path';

function owner(path) {
  return /^(?:app|features)\/(platform|property)(?:\/|$)/.exec(path)?.[1];
}

export function createAdminBoundaryRule(sourceRoot) {
  const pathWithinSource = (path) =>
    relative(sourceRoot, path).split(sep).join('/');
  return {
    meta: {
      type: 'problem',
      schema: [],
      messages: {
        common: '共用模块不能依赖具体后台应用或业务模块。',
        foreign: '平台与物业业务模块不能互相依赖。',
        assembly: '端业务模块不能依赖应用组装或跨端注册入口。',
      },
    },
    create(context) {
      const source = pathWithinSource(context.filename);
      const sourceOwner = owner(source);
      const common =
        /^(?:auth|shared|components)\//.test(source) ||
        /^features\/(?:auth|profile)\//.test(source);
      function check(node) {
        const value =
          node?.type === 'TemplateLiteral' && node.expressions.length === 0
            ? node.quasis[0].value.cooked
            : node?.value;
        if (
          typeof value !== 'string' ||
          (!value.startsWith('.') && !value.startsWith('@/'))
        )
          return;
        const target = pathWithinSource(
          value.startsWith('@/')
            ? resolve(sourceRoot, value.slice(2))
            : resolve(dirname(context.filename), value),
        );
        const targetOwner = owner(target);
        const applicationTarget = /^app(?:[/.]|$)/.test(target);
        let messageId;
        if (common && (targetOwner || applicationTarget)) messageId = 'common';
        else if (sourceOwner && targetOwner && sourceOwner !== targetOwner)
          messageId = 'foreign';
        else if (
          sourceOwner &&
          ((source.startsWith('features/') && applicationTarget) ||
            /^app\/admin-routes(?:\.|$)/.test(target))
        )
          messageId = 'assembly';
        if (messageId) context.report({ node, messageId });
      }
      return {
        ImportDeclaration: (node) => check(node.source),
        ExportNamedDeclaration: (node) => check(node.source),
        ExportAllDeclaration: (node) => check(node.source),
        ImportExpression: (node) => check(node.source),
        CallExpression: (node) => {
          if (
            node.callee.type === 'Identifier' &&
            node.callee.name === 'require'
          )
            check(node.arguments[0]);
        },
        TSImportEqualsDeclaration: (node) =>
          check(node.moduleReference.expression),
      };
    },
  };
}
