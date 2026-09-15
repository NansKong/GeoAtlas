import { formatDistanceToNow, formatDistanceStrict } from "date-fns";

/**
 * Safely parses a date string/value/Date object. Returns null if the value is
 * null, undefined, empty, or produces an Invalid Date.
 */
export function safeDate(value: string | number | Date | null | undefined): Date | null {
  if (value == null || value === "") return null;
  if (value instanceof Date) {
    return isNaN(value.getTime()) ? null : value;
  }
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Formats a date string/value as "X ago" using date-fns.
 * Returns fallback (default "—") if the date is invalid.
 */
export function safeDistanceToNow(
  value: string | number | Date | null | undefined,
  fallback = "—"
): string {
  const d = safeDate(value);
  if (!d) return fallback;
  try {
    return formatDistanceToNow(d, { addSuffix: true });
  } catch {
    return fallback;
  }
}

/**
 * Formats two dates as a strict distance string using date-fns.
 * Returns fallback if either date is invalid.
 */
export function safeDistanceStrict(
  dateLeft: string | number | Date | null | undefined,
  dateRight: string | number | Date | null | undefined,
  fallback = "—"
): string {
  const dl = safeDate(dateLeft);
  const dr = safeDate(dateRight);
  if (!dl || !dr) return fallback;
  try {
    return formatDistanceStrict(dl, dr);
  } catch {
    return fallback;
  }
}

/**
 * Safely calculates difference in seconds between two dates (dl - dr).
 * Returns 0 if either date is invalid.
 */
export function safeDifferenceInSeconds(
  dateLeft: string | number | Date | null | undefined,
  dateRight: string | number | Date | null | undefined
): number {
  const dl = safeDate(dateLeft);
  const dr = safeDate(dateRight);
  if (!dl || !dr) return 0;
  return Math.max(0, Math.floor((dl.getTime() - dr.getTime()) / 1000));
}
