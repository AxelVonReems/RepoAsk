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
  syncedAt: string;
}