// Must match the API slug rules (api/silo/schemas/{game,library}.py).
export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
export const SLUG_MAX_LENGTH = 64

export function slugify(s: string): string {
  // Mirrors the backend (services/entities.py): strip, truncate, re-strip.
  return s
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, SLUG_MAX_LENGTH)
    .replace(/-+$/, "")
}

export function isValidSlug(s: string): boolean {
  return s.length <= SLUG_MAX_LENGTH && SLUG_PATTERN.test(s)
}
