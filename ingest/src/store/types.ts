// Normalized SQLite entity
export interface RepositoryRecord {
  id: string;
  name: string;
  fullName: string;
  url: string;
  description: string | null;
  metric: number; // stargazers_count
  forks: number;
  openIssues: number;
  topics: string[]; // stored as a JSON array in a TEXT column
  syncedAt: string;
}

// README content for one repository
export interface ReadmeRecord {
  repoId: string;
  etag: string | null;
  content: string;
  contentSha: string; // sha256 hex of content
  sizeBytes: number;
  fetchedAt: string;
}

export type ReadmeUpsertResult = 'inserted' | 'updated' | 'unchanged';