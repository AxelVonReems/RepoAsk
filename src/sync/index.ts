import { fileURLToPath } from 'node:url';
import { config } from '../config.js';
import { initDB } from '../store/db.js';
import { upsertRepositories } from '../store/repository.js';
import { fetchWithRetry, parseNextPageUrl } from './client.js';
import { GitHubPageSchema } from './types.js';
import type { GitHubRepoPayload, SyncSummary } from './types.js';
import type { RepositoryRecord } from '../store/types.js';

export async function sync(): Promise<SyncSummary> {
  const startTime = performance.now();

  const summary: SyncSummary = {
    fetched: 0,
    inserted: 0,
    updated: 0,
    skipped: 0,
    apiCalls: 0,
    errors: 0,
    capped: false,
    durationMs: 0
  };

  try {
    initDB();

    let currentUrl: string | null = config.github.syncUrl;
    let pagesProcessed = 0;

    while (currentUrl) {
      if (pagesProcessed >= config.github.maxPages) {
        summary.capped = true;
        break;
      }

      // Fetch as unknown to force Zod to validate the raw boundary
      const { data: rawData, headers } = await fetchWithRetry<unknown>(currentUrl);
      summary.apiCalls++;
      pagesProcessed++;

      const parseResult = GitHubPageSchema.safeParse(rawData);

      if (!parseResult.success) {
        console.warn('Zod validation failed for page payload');
        summary.errors++;
        break;
      }

      const payloads: GitHubRepoPayload[] = parseResult.data;
      summary.fetched += payloads.length;

      const validRecords: RepositoryRecord[] = [];

      for (const payload of payloads) {
        try {
          validRecords.push({
            id: payload.id.toString(),
            name: payload.name,
            fullName: payload.full_name,
            url: payload.html_url,
            description: payload.description ?? null,
            metric: payload.stargazers_count ?? 0,
            forks: payload.forks_count ?? 0,
            openIssues: payload.open_issues_count ?? 0,
            syncedAt: new Date().toISOString()
          });
        } catch (error: unknown) {
          console.warn(error instanceof Error ? error.message : String(error));
          summary.errors++;
          summary.skipped++;
        }
      }

      if (validRecords.length > 0) {
        const { inserted, updated } = upsertRepositories(validRecords);
        summary.inserted += inserted;
        summary.updated += updated;
      }

      // Read the 'link' header using Axios' raw or parsed headers
      const linkHeader = typeof headers.get === 'function' 
        ? (headers.get('link') as string | undefined) 
        : (headers['link'] as string | undefined);

      currentUrl = parseNextPageUrl(linkHeader);
    }

    summary.durationMs = Math.round(performance.now() - startTime);

    return summary;

  } catch (error: unknown) {
    summary.durationMs = Math.round(performance.now() - startTime);

    console.error('FATAL ERROR DURING SYNC:', error instanceof Error ? error.message : String(error));
    console.error('Partial Sync Summary:');
    console.error(JSON.stringify(summary, null, 2));

    throw summary;
  }
}

// Only auto-execute if this file is run directly (e.g., npm run sync)
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  sync()
    .then((summary) => {
      console.log('Sync completed successfully.');
      console.log(JSON.stringify(summary, null, 2));
      process.exit(0);
    })
    .catch((err) => {
      console.error('Fatal sync error:', err);
      process.exit(1);
    });
}