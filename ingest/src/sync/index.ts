import { fileURLToPath } from 'node:url';
import { config } from '../config.js';
import { initDB } from '../store/db.js';
import { upsertRepositories } from '../store/repository.js';
import { fetchWithRetry, parseNextPageUrl, sleep } from './client.js';
import { parsePage } from './page.js';
import { resolveSource } from './source.js';
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

    const source = resolveSource(config.github.source, config.github.maxPages);
    console.log(`Syncing ${config.github.source} (up to ${source.maxPages} pages)`);

    let currentUrl: string | null = source.url;
    let pagesProcessed = 0;

    while (currentUrl) {
      if (pagesProcessed >= source.maxPages) {
        summary.capped = true;
        break;
      }

      // Search API has a separate per-minute limit, so space out page requests
      if (source.kind === 'search' && pagesProcessed > 0) {
        await sleep(config.github.searchPageDelayMs);
      }

      // Fetch as unknown to force Zod to validate the raw boundary
      const { data: rawData, headers } = await fetchWithRetry<unknown>(currentUrl);
      summary.apiCalls++;
      pagesProcessed++;

      const payloads: GitHubRepoPayload[] | null = parsePage(source.kind, rawData);

      if (!payloads) {
        console.warn('Zod validation failed for page payload');
        summary.errors++;
        break;
      }

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