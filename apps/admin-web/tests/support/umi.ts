import { createRequire } from 'node:module';
import type { HistoryRouterProps } from 'react-router-dom';

export { generatePath, matchPath } from 'react-router-dom';

// Exercise Umi's runtime libraries without loading the generated application.
const require = createRequire(import.meta.url);
const requireFromRouter = createRequire(require.resolve('react-router-dom'));
const { createBrowserHistory } = requireFromRouter('history') as {
  createBrowserHistory: () => HistoryRouterProps['history'];
};

export const history = createBrowserHistory();
