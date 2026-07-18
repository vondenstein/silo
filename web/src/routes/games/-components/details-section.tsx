import { useAppForm } from "@/hooks/form"
import { FieldKey } from "@/lib/api/model"
import type { GameDetail, GamePatch } from "@/lib/api/model"
import { libraryListQueryOptions } from "@/lib/queries"
import { useEditSection } from "@/routes/games/-components/edit-session"
import { FieldRow } from "@/routes/games/-components/field-row"
import { GAME_TYPE_OPTIONS, WRAPPER_OPTIONS } from "@/routes/games/-components/labels"
import { useStore } from "@tanstack/react-form"
import { useSuspenseInfiniteQuery } from "@tanstack/react-query"
import { useState } from "react"
import * as z from "zod"

const NULLABLE_FIELDS = [
  "sort_title",
  "first_release_date",
  "game_type",
  "wrapper",
  "description_short",
  "description_full",
] as const

type FormValues = Record<(typeof NULLABLE_FIELDS)[number] | "title" | "library_id", string>

function buildPatch(values: FormValues, baseline: FormValues): GamePatch {
  const patch: GamePatch = {}
  if (values.title.trim() !== baseline.title) patch.title = values.title.trim()
  if (values.library_id !== baseline.library_id) patch.library_id = values.library_id
  for (const key of NULLABLE_FIELDS) {
    if (values[key] === baseline[key]) continue
    // Form values originate from the enum/date unions; "" ⇄ null at this boundary.
    Object.assign(patch, { [key]: values[key] === "" ? null : values[key] })
  }
  return patch
}

export function DetailsSection({ game }: { game: GameDetail }) {
  // Baseline pinned at mount: mid-dialog refetches must not shift the diff
  // under touched form values; the shell remounts this section to re-baseline.
  const [baseline] = useState<FormValues>(() => ({
    title: game.title,
    library_id: game.library_id,
    sort_title: game.sort_title ?? "",
    first_release_date: game.first_release_date ?? "",
    game_type: game.game_type ?? "",
    wrapper: game.wrapper ?? "",
    description_short: game.description_short ?? "",
    description_full: game.description_full ?? "",
  }))
  const { data: libraryPages } = useSuspenseInfiniteQuery(libraryListQueryOptions())
  const libraryOptions = libraryPages.pages
    .flatMap((page) => page.items)
    .map((library) => ({ value: library.id, label: library.name }))

  const form = useAppForm({
    defaultValues: baseline,
    validators: {
      onChange: z.object({
        title: z.string().trim().min(1, "Required"),
        library_id: z.string().min(1, "Required"),
        sort_title: z.string(),
        first_release_date: z.string(),
        game_type: z.string(),
        wrapper: z.string(),
        description_short: z.string(),
        description_full: z.string(),
      }),
    },
  })
  const values = useStore(form.store, (state) => state.values)
  const isValid = useStore(form.store, (state) => state.isValid)
  const dirty = Object.keys(buildPatch(values, baseline)).length > 0

  const session = useEditSection("details", { dirty, invalid: !isValid }, () => {
    const patch = buildPatch(form.state.values, baseline)
    return Object.keys(patch).length > 0 ? { patch } : null
  })

  return (
    <div className="space-y-4">
      <FieldRow fieldKey={FieldKey.title} locks={session.locks} onToggle={session.toggleLock}>
        <form.AppField
          name="title"
          listeners={{ onChange: () => session.lockOnChange(FieldKey.title) }}
        >
          {(f) => <f.TextField label="Title" />}
        </form.AppField>
      </FieldRow>
      {/* Library is structural (not a metadata field) — no lock. */}
      <form.AppField name="library_id">
        {(f) => <f.SelectField label="Library" options={libraryOptions} clearable={false} />}
      </form.AppField>
      <FieldRow fieldKey={FieldKey.sort_title} locks={session.locks} onToggle={session.toggleLock}>
        <form.AppField
          name="sort_title"
          listeners={{ onChange: () => session.lockOnChange(FieldKey.sort_title) }}
        >
          {(f) => <f.TextField label="Sort title" description="Used for alphabetical ordering." />}
        </form.AppField>
      </FieldRow>
      <FieldRow
        fieldKey={FieldKey.first_release_date}
        locks={session.locks}
        onToggle={session.toggleLock}
      >
        <form.AppField
          name="first_release_date"
          listeners={{ onChange: () => session.lockOnChange(FieldKey.first_release_date) }}
        >
          {(f) => <f.DateField label="First release date" />}
        </form.AppField>
      </FieldRow>
      <FieldRow fieldKey={FieldKey.game_type} locks={session.locks} onToggle={session.toggleLock}>
        <form.AppField
          name="game_type"
          listeners={{ onChange: () => session.lockOnChange(FieldKey.game_type) }}
        >
          {(f) => <f.SelectField label="Game type" options={GAME_TYPE_OPTIONS} />}
        </form.AppField>
      </FieldRow>
      <FieldRow fieldKey={FieldKey.wrapper} locks={session.locks} onToggle={session.toggleLock}>
        <form.AppField
          name="wrapper"
          listeners={{ onChange: () => session.lockOnChange(FieldKey.wrapper) }}
        >
          {(f) => <f.SelectField label="Wrapper" options={WRAPPER_OPTIONS} />}
        </form.AppField>
      </FieldRow>
      <FieldRow
        fieldKey={FieldKey.description_short}
        locks={session.locks}
        onToggle={session.toggleLock}
      >
        <form.AppField
          name="description_short"
          listeners={{ onChange: () => session.lockOnChange(FieldKey.description_short) }}
        >
          {(f) => <f.TextareaField label="Short description" />}
        </form.AppField>
      </FieldRow>
      <FieldRow
        fieldKey={FieldKey.description_full}
        locks={session.locks}
        onToggle={session.toggleLock}
      >
        <form.AppField
          name="description_full"
          listeners={{ onChange: () => session.lockOnChange(FieldKey.description_full) }}
        >
          {(f) => <f.TextareaField label="Full description" />}
        </form.AppField>
      </FieldRow>
    </div>
  )
}
