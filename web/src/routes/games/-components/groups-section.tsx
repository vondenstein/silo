import { Badge } from "@/components/ui/badge"
import { Field, FieldLabel } from "@/components/ui/field"
import type { GameDetail, GamePatch } from "@/lib/api/model"
import { useEditSection } from "@/routes/games/-components/edit-session"
import { FieldRow } from "@/routes/games/-components/field-row"
import { SectionHeader } from "@/routes/games/-components/section-header"
import { XIcon } from "@phosphor-icons/react"
import { useState } from "react"

const GROUP_FIELDS = [
  { key: "genres", label: "Genres" },
  { key: "themes", label: "Themes" },
  { key: "tags", label: "Tags" },
  { key: "engines", label: "Engines" },
  { key: "modes", label: "Modes" },
  { key: "developers", label: "Developers" },
  { key: "publishers", label: "Publishers" },
  { key: "series", label: "Series" },
] as const

type GroupKey = (typeof GROUP_FIELDS)[number]["key"]

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i])
}

export function GroupsSection({ game }: { game: GameDetail }) {
  // Baseline pinned at mount — see details-section; the shell remounts to re-baseline.
  const [baseline] = useState(
    () =>
      Object.fromEntries(
        GROUP_FIELDS.map((field) => [field.key, game[field.key].map((entity) => entity.name)]),
      ) as Record<GroupKey, string[]>,
  )
  const [values, setValues] = useState(baseline)

  const dirtyFields = GROUP_FIELDS.filter(
    (field) => !sameList(values[field.key], baseline[field.key]),
  )
  const session = useEditSection("groups", { dirty: dirtyFields.length > 0 }, () => {
    if (dirtyFields.length === 0) return null
    const patch: GamePatch = {}
    for (const field of dirtyFields) {
      patch[field.key] = values[field.key]
    }
    return { patch }
  })

  const setField = (key: GroupKey, names: string[]) => {
    setValues((current) => ({ ...current, [key]: names }))
    session.lockOnChange(key)
  }

  return (
    <div className="flex flex-1 flex-col gap-4">
      <SectionHeader
        title="Groups"
        description="Genres, tags, people, and series. Locking a group keeps your edits through metadata fetches."
      />
      <div className="space-y-4">
        {GROUP_FIELDS.map((field) => (
          <FieldRow
            key={field.key}
            fieldKey={field.key}
            locks={session.locks}
            onToggle={session.toggleLock}
          >
            <ChipsField
              label={field.label}
              values={values[field.key]}
              onChange={(names) => setField(field.key, names)}
            />
          </FieldRow>
        ))}
      </div>
    </div>
  )
}

function ChipsField({
  label,
  values,
  onChange,
}: {
  label: string
  values: string[]
  onChange: (values: string[]) => void
}) {
  const [draft, setDraft] = useState("")

  const add = () => {
    const value = draft.trim()
    if (value && !values.includes(value)) onChange([...values, value])
    setDraft("")
  }
  const remove = (value: string) => onChange(values.filter((v) => v !== value))

  return (
    <Field>
      <FieldLabel htmlFor={`chips-${label}`}>{label}</FieldLabel>
      <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-input bg-transparent px-2 py-1.5 shadow-xs dark:bg-input/30">
        {values.map((value) => (
          <Badge key={value} variant="secondary" className="gap-1 pr-1">
            {value}
            <button
              type="button"
              onClick={() => remove(value)}
              aria-label={`Remove ${value}`}
              className="rounded-sm hover:text-foreground/70 focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
            >
              <XIcon className="size-3" />
            </button>
          </Badge>
        ))}
        <input
          id={`chips-${label}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={add}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              add()
            }
            if (e.key === "Backspace" && draft === "" && values.length > 0) {
              onChange(values.slice(0, -1))
            }
          }}
          placeholder={values.length === 0 ? "Type a name and press Enter" : undefined}
          className="min-w-28 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
    </Field>
  )
}
