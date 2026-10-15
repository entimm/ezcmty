import type { IApi } from '@umijs/max';
import { join } from 'node:path';

export default function setupTypes(api: IApi) {
  if (api.name !== 'setup') return;

  // Umi setup deletes its target directory before generating files.
  const absTmpPath = join(api.paths.absSrcPath, '.umi-types');
  api.modifyPaths((paths) => ({
    ...paths,
    absTmpPath,
  }));
  // Umi resolves aliases before applying modifyPaths.
  api.modifyConfig({
    stage: Number.POSITIVE_INFINITY,
    fn: (config) => ({
      ...config,
      alias: { ...config.alias, '@@': absTmpPath },
    }),
  });
  api.modifyTSConfig((config) => ({
    ...config,
    compilerOptions: {
      ...config.compilerOptions,
      paths: {
        ...config.compilerOptions.paths,
        '@@/*': ['./*'],
        [`${api.appData.umi.importSource}/typings`]: ['./typings'],
      },
    },
  }));
}
