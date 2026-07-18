import type { GameDetail } from "@/lib/api/model"
import { slugify } from "@/lib/slug"

export type ManualDoc = {
  label: string
  url: string
  artifactName: string
}

const ROMAN_VALUES: Record<string, number> = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 }
const ROMAN_PATTERN = /^m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$/

// Sequel numerals only — a cap of 30 keeps real words like "mix" (1009) unconverted.
function romanToArabic(token: string): string | null {
  if (!token || !ROMAN_PATTERN.test(token)) return null
  let total = 0
  for (let i = 0; i < token.length; i++) {
    const value = ROMAN_VALUES[token[i]]
    const next = i + 1 < token.length ? ROMAN_VALUES[token[i + 1]] : 0
    total += value < next ? -value : value
  }
  return total <= 30 ? String(total) : null
}

function tokenize(text: string): string[] {
  return slugify(text)
    .split("-")
    .filter(Boolean)
    .map((token) => romanToArabic(token) ?? token)
}

function overlap(gameTokens: Set<string>, text: string): number {
  return tokenize(text).filter((token) => gameTokens.has(token)).length
}

// The actual manual first: docs from "manual"-named artifacts, best title match wins.
export function pickPrimary(docs: ManualDoc[], game: GameDetail): ManualDoc {
  const eligible = docs.filter((doc) => doc.artifactName.toLowerCase().includes("manual"))
  const pool = eligible.length > 0 ? eligible : docs
  const gameTokens = new Set(tokenize(game.sort_title ?? game.title))
  let best = pool[0]
  let bestScore = -1
  for (const doc of pool) {
    const score = overlap(gameTokens, doc.label)
    if (score > bestScore) {
      best = doc
      bestScore = score
    }
  }
  return best
}
