import { fileURLToPath } from 'node:url';
import { config } from '../config.js';
import { initDB } from '../store/db.js';
import { deleteRepositoriesSyncedBefore, upsertRepositories } from '../store/repository.js';
import { getReadmeEtag, toReadmeRecord, touchReadme, upsertReadme } from '../store/readmes.js';
import { fetchReadme, fetchWithRetry, parseNextPageUrl, sleep } from './client.js';
import { parsePage } from './page.js';
import { resolveSource } from './source.js';
import type { GitHubRepoPayload, SyncSummary } from './types.js';
import type { RepositoryRecord } from '../store/types.js';

// Fetches READMEs one repository at a time. GitHub recommends serial requests
// to avoid secondary rate limits. A failing repository is counted, not fatal.
async function syncReadmes(repos: Pick<RepositoryRecord, 'id' | 'fullName'>[], summary: SyncSummary): Promise<void> {
  console.log(`Fetching READMEs for ${repos.length} repositories`);

  for (const [index, repo] of repos.entries()) {
    try {
      const result = await fetchReadme(repo.fullName, getReadmeEtag(repo.id));
      summary.apiCalls++;

      if (result.status === 'missing') {
        summary.readmes.missing++;
      } else if (result.status === 'not_modified') {
        touchReadme(repo.id);
        summary.readmes.notModified++;
      } else {
        summary.readmes[upsertReadme(toReadmeRecord(repo.id, result.content, result.etag))]++;
      }
    } catch (error: unknown) {
      console.warn(`README ${repo.fullName}: ${error instanceof Error ? error.message : String(error)}`);
      summary.readmes.errors++;
    }

    if ((index + 1) % 100 === 0) {
      console.log(`  ${index + 1}/${repos.length} READMEs checked`);
    }
  }
}

export async function sync(): Promise<SyncSummary> {
  const startTime = performance.now();

  const summary: SyncSummary = {
    fetched: 0,
    inserted: 0,
    updated: 0,
    skipped: 0,
    removed: 0,
    apiCalls: 0,
    errors: 0,
    capped: false,
    durationMs: 0,
    readmes: { inserted: 0, updated: 0, unchanged: 0, notModified: 0, missing: 0, errors: 0 }
  };

  const syncedRepos: Pick<RepositoryRecord, 'id' | 'fullName'>[] = [];
  const runStartedAt = new Date().toISOString();

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
            topics: payload.topics,
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
        syncedRepos.push(...validRecords.map(({ id, fullName }) => ({ id, fullName })));
      }

      // Read the 'link' header using Axios' raw or parsed headers
      const linkHeader = typeof headers.get === 'function' 
        ? (headers.get('link') as string | undefined) 
        : (headers['link'] as string | undefined);

      currentUrl = parseNextPageUrl(linkHeader);
    }

    // Remove repos that are no longer in the source (e.g. fell out of the top 1,000).
    // Only after a clean run: a partial or empty run must never wipe good data.
    if (summary.errors === 0 && syncedRepos.length > 0) {
      summary.removed = deleteRepositoriesSyncedBefore(runStartedAt);
    } else {
      console.warn('Skipping stale repository cleanup: repository sync was incomplete.');
    }

    await syncReadmes(syncedRepos, summary);

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