// Report an unexpected Umi dev child exit to the batch supervisor.
process.exitCode = 1;
void (async () => {
  await import('../../../scripts/generate_api_types.mjs');
  process.argv.splice(2, 0, 'dev');
  await import('@umijs/max/bin/max.js');
})();
