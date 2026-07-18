import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { GameDetail } from "@/lib/api/model"
import { useEditSection } from "@/routes/games/-components/edit-session"
import { SectionHeader } from "@/routes/games/-components/section-header"
import { PlusIcon, XIcon } from "@phosphor-icons/react"
import { useState } from "react"

type SerialRow = { value: string; comment: string }

function cleaned(rows: SerialRow[]): { value: string; comment: string | null }[] {
  return rows
    .map((row) => ({ value: row.value.trim(), comment: row.comment.trim() || null }))
    .filter((row) => row.value)
}

export function SerialsSection({ game }: { game: GameDetail }) {
  // Baseline pinned at mount — see details-section; the shell remounts to re-baseline.
  const [baseline] = useState<SerialRow[]>(() =>
    game.serials.map((serial) => ({ value: serial.value, comment: serial.comment ?? "" })),
  )
  const [rows, setRows] = useState(baseline)

  const dirty = JSON.stringify(cleaned(rows)) !== JSON.stringify(cleaned(baseline))
  useEditSection("serials", { dirty }, () => (dirty ? { patch: { serials: cleaned(rows) } } : null))

  const setRow = (index: number, patch: Partial<SerialRow>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)))

  return (
    <div className="flex flex-1 flex-col gap-4">
      <SectionHeader
        title="Serial numbers"
        description="CD keys, disc serials, catalog numbers — your copy's provenance. Never touched by metadata fetches."
      />
      <div className="space-y-2">
        {rows.map((row, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              value={row.value}
              onChange={(e) => setRow(index, { value: e.target.value })}
              placeholder="Serial"
              className="font-mono"
            />
            <Input
              value={row.comment}
              onChange={(e) => setRow(index, { comment: e.target.value })}
              placeholder="Comment (optional)"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
              aria-label="Remove serial"
            >
              <XIcon />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setRows((current) => [...current, { value: "", comment: "" }])}
        >
          <PlusIcon /> Add serial
        </Button>
      </div>
    </div>
  )
}
