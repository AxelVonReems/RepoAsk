import { initDB } from './store/db.js';
import { sync } from './sync/index.js';
import { getTopRepositories } from './tool/index.js';

async function main() {
  console.log('🚀 Starting end-to-end pipeline...\n');

  // Ensure DB schema exists
  initDB();

  // Run the background sync worker
  console.log('📦 Synchronizing repositories from GitHub...');
  const summary = await sync();
  console.log('\n📊 Sync Summary:');
  console.log(JSON.stringify(summary, null, 2));

  // Query the store via the AI Agent Tool
  console.log('\n🤖 Querying AI Agent Tool (Top 5 Repositories):');
  const agentOutput = getTopRepositories(5);
  console.log(agentOutput);

  console.log('\n✨ Pipeline completed successfully.');
}

main().catch((err: unknown) => {
  console.error('❌ Pipeline failed:', err);
  process.exit(1);
});