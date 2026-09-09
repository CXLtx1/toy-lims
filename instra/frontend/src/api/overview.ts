import type { SampleListItem } from "./types";

export interface PortSample extends SampleListItem {
  task_total: number;
  task_completed: number;
  instrument_ids: number[];
}

export interface PortAudit {
  id: number;
  created_at: string | null;
  username: string;
  action: string;
  action_label: string;
  entity_type: string;
  entity_id: string;
  entity_label: string;
  reason: string;
}

export interface SampleAudit extends Omit<PortAudit, "entity_type" | "entity_id"> {
  entity_type?: string;
  entity_id?: string;
  changes: { field: string; label: string; before: unknown; after: unknown }[];
  has_snapshot: boolean;
}

export interface AuditSceneContext {
  ok: boolean;
  supported: boolean;
  reason?: string;
  audit: { id: number; created_at: string | null; username: string; action_label: string };
  sample?: { id: number; name: string; lims_no: string | null; status: string };
  locator?: { sample_id: number; sample_analyte_id: number; reading_id: number; field: "raw" };
  values?: Record<"before" | "after" | "current", { available: boolean; value: number | null }>;
  warnings?: string[];
}

export interface AuditPage {
  items: PortAudit[];
  has_more: boolean;
  next_before_id: number | null;
}

export interface PortInstrument {
  id: number;
  name: string;
  itype: string;
  task_total: number;
  open_tasks: number;
  open_samples: number;
  completed: number;
}

export interface Overview {
  ok: boolean;
  generated_at: string;
  samples: { total: number; by_status: Record<string, number> };
  instruments: PortInstrument[];
  unassigned: { open_tasks: number; open_samples: number };
  xrf: { requested_samples: number; awaiting_scan: number; linked_samples: number };
  recent_audits: AuditPage;
}
