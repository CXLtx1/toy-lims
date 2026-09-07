import dayjs from "dayjs";

import type { XrfUnit } from "./api/types";

const STATUS_LABELS: Record<string, string> = {
  received: "已登记",
  in_progress: "制样中",
  measuring: "测量中",
  partially_done: "部分完成",
  completed: "待审核",
  pending_review: "待审核",
  reviewed: "已审核",
  reported: "已出报告",
  cancelled: "已作废",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status || "—";
}

export function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm") : String(value);
}

/** 与后端 domain/format.py 一致的 5 位有效数字格式化。 */
export function fmtNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (!Number.isFinite(value)) return String(value);
  return Number(value.toPrecision(5)).toString();
}

export function defaultXrfUnit(...values: (number | null | undefined)[]): XrfUnit {
  const maximum = Math.max(0, ...values.flatMap((value) =>
    value == null ? [] : [Math.abs(value)]));
  if (maximum >= 0.1) return "%";
  if (maximum * 10_000 >= 1) return "ppm";
  return "ppb";
}

export function fmtXrfValue(value: number | null | undefined, unit?: XrfUnit): string {
  if (value == null) return "—";
  const displayUnit = unit ?? defaultXrfUnit(value);
  const multiplier = displayUnit === "%" ? 1 : displayUnit === "ppm" ? 10_000 : 10_000_000;
  return `${fmtNumber(value * multiplier)} ${displayUnit}`;
}
