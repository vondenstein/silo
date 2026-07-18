export function formatSize(bytes: number | null): string {
  if (bytes == null) return "—"
  if (bytes < 1024) return `${bytes} B`
  // Pick the unit after rounding, so 1048575 B is "1.0 MB", never "1024.0 KB".
  const kb = bytes / 1024
  if (Math.round(kb * 10) < 10240) return `${kb.toFixed(1)} KB`
  const mb = kb / 1024
  if (Math.round(mb * 10) < 10240) return `${mb.toFixed(1)} MB`
  return `${(mb / 1024).toFixed(2)} GB`
}
