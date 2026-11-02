// Agent tool contracts
export interface ToolItem {
  name: string;
  url: string;
  description: string | null;
  stars: number;
  last_sync: string;
}

export interface RepositoryRow {
  name: string;
  url: string;
  description: string | null;
  metric: number;
  syncedAt: string;
}
