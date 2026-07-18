function ago(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`
}

/** Format a date as a short relative-time string. Returns the label and a stale flag. */
export function relativeTime(
  value: string | Date | null,
  staleDays = 30,
): { label: string; stale: boolean } {
  if (!value) return { label: "Never", stale: false }
  const d = typeof value === "string" ? new Date(value) : value
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000)
  const stale = days >= staleDays
  if (days <= 0) return { label: "today", stale: false }
  if (days === 1) return { label: "yesterday", stale }
  if (days < 30) return { label: ago(days, "day"), stale }
  const months = Math.floor(days / 30)
  if (months < 12) return { label: ago(months, "month"), stale }
  // days 360–364 floor to 0 years; they belong to the year bucket regardless.
  return { label: ago(Math.max(1, Math.floor(days / 365)), "year"), stale }
}
