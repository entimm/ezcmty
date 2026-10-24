// Report an unexpected Umi dev child exit to the batch supervisor.
process.exitCode = 1;
process.argv.splice(2, 0, 'dev');
void import('@umijs/max/bin/max.js');
