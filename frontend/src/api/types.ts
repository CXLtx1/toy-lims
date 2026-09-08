export const pages = ['intake', 'data', 'instrument', 'results', 'report', 'audit', 'users', 'settings', 'about'] as const;
export type PageName = typeof pages[number];
export interface User { id: number | null; username: string; display_name: string; permissions: string[]; virtual?: boolean }
export interface Terminal { id: number | null; name: string; kind: 'standard' | 'personal' | 'admin' }
export interface Session {
  ok: boolean; csrf_token: string; authenticated: boolean; setup_required: boolean;
  terminal: Terminal | null; user: User | null; authorization_required: boolean;
  requireHTTPS: boolean; min_password_length: number;
}
export interface Meta {
  sample_statuses: Record<string, string>;
  sample_tags: { name: string; count: number }[];
  terminal: Terminal | null;
  current_user: User | null;
  authorized_user: User | null;
  authorization_required: boolean;
  capabilities: Record<string, string>;
}
export interface CurrentSample { id: number; name: string; category: string; lims_no: string; status: string }
export interface SiteStatus {
  revision: number; server_time: string;
  latest_change?: { display_name: string; username: string; created_at: string; action: string; reason: string; changes: { label: string; before: unknown; after: unknown }[] } | null;
}
