import type { IApi } from '@umijs/max';

export function configureDevServer(api: IApi, port: number) {
  if (api.name !== 'dev') return;

  process.env.HOST = '127.0.0.1';
  process.env.PORT = String(port);

  api.modifyAppData({
    stage: Number.POSITIVE_INFINITY,
    fn: (data) => {
      if (data.port !== port) {
        throw new Error(`管理后台端口 ${port} 已被占用；不会自动切换端口。`);
      }
      return { ...data, host: '127.0.0.1' };
    },
  });
}

export default function devServer(api: IApi) {
  configureDevServer(api, 5173);
}
