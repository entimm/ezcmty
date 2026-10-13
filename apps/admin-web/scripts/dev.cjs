// Umi's dev parent drops its child's exit code; unexpected exits must fail.
process.exitCode = 1;
process.argv.splice(2, 0, 'dev');
void import('@umijs/max/bin/max.js');
