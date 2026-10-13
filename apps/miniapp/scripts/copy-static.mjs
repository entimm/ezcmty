import { cp, rm, readFile, writeFile } from 'node:fs/promises';

await rm('dist', { recursive: true, force: true });
await cp('src', 'dist', {
  recursive: true,
  filter: (source) => !source.endsWith('.ts'),
});

const project = JSON.parse(await readFile('project.config.json', 'utf8'));
project.miniprogramRoot = './';
project.appid = process.env.MINIAPP_APP_ID || project.appid;
await writeFile('dist/project.config.json', JSON.stringify(project, null, 2));

const app = JSON.parse(await readFile('dist/app.json', 'utf8'));
app.window.navigationBarTitleText =
  process.env.MINIAPP_APP_NAME || app.window.navigationBarTitleText;
await writeFile('dist/app.json', JSON.stringify(app, null, 2));
