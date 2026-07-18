import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useAppForm } from "@/hooks/form"
import {
  getGetGameQueryKey,
  getJob,
  getListGamesInfiniteQueryKey,
  useCancelUpload,
  useFinalizeUpload,
} from "@/lib/api/client"
import { ArtifactKind } from "@/lib/api/model"
import type { SignatureMatchOut, StageOut } from "@/lib/api/model"
import { JOB_LIST_KEYS, libraryListQueryOptions } from "@/lib/queries"
import { queryClient } from "@/lib/query-client"
import { formatSize } from "@/lib/format-size"
import { SLUG_MAX_LENGTH, SLUG_PATTERN, slugify } from "@/lib/slug"
import { cn } from "@/lib/utils"
import { CheckCircleIcon, FileIcon } from "@phosphor-icons/react"
import { useSuspenseInfiniteQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import { toast } from "sonner"
import * as z from "zod"

// DAT titles carry qualifiers like "(USA) (Rev 1)" — strip them for prefills.
function cleanDatName(gameName: string): string {
  return gameName.replace(/\s*\([^)]*\)/g, "").trim()
}

// Fire-and-forget: toasts the identify chain's outcome. Deliberately not a hook —
// finalize navigates away immediately and the poll must outlive this component.
// The worker is sequential, so an identify queued behind a long import can wait
// minutes: 2s polls for the first 30s, then 10s polls up to 5 minutes.
async function watchIdentification(jobId: string, gameId: string) {
  const started = Date.now()
  while (Date.now() - started < 5 * 60 * 1000) {
    await new Promise((resolve) =>
      setTimeout(resolve, Date.now() - started < 30_000 ? 2000 : 10_000),
    )
    const job = await getJob(jobId).catch(() => null)
    if (!job || job.status === "pending" || job.status === "running") continue
    if (job.status !== "completed") {
      toast.warning("Identification failed — check Jobs")
    } else {
      const result = job.result as { matched?: boolean; name?: string | null } | null
      if (result?.matched) {
        toast.success(
          result.name
            ? `Identified as "${result.name}" — fetching metadata`
            : "Identified — fetching metadata",
        )
      } else {
        toast.info("No confident IGDB match — set the identity from the game page")
      }
    }
    // The user was navigated to the game page at finalize; surface the outcome there.
    queryClient.invalidateQueries({ queryKey: getGetGameQueryKey(gameId) })
    queryClient.invalidateQueries({ queryKey: getListGamesInfiniteQueryKey() })
    return
  }
  toast.info("Identification still queued — follow it in Jobs")
}

const KIND_OPTIONS: { value: ArtifactKind; label: string }[] = [
  { value: ArtifactKind.installer, label: "Installer" },
  { value: ArtifactKind.patch, label: "Patch" },
  { value: ArtifactKind.language_pack, label: "Language pack" },
  { value: ArtifactKind.disc, label: "Disc image" },
  { value: ArtifactKind.rom, label: "ROM" },
  { value: ArtifactKind.extra, label: "Extra" },
  { value: ArtifactKind.save, label: "Save" },
  { value: ArtifactKind.manual, label: "Manual" },
  { value: ArtifactKind.other, label: "Other" },
]

export function FinalizeStep({ stage, onReset }: { stage: StageOut; onReset: () => void }) {
  const navigate = useNavigate()
  const { data } = useSuspenseInfiniteQuery(libraryListQueryOptions())
  const libraries = data.pages.flatMap((page) => page.items)
  const [chosen, setChosen] = useState<SignatureMatchOut | null>(null)

  const finalizeMutation = useFinalizeUpload({
    mutation: {
      meta: {
        errorToast: "Failed to add game",
        invalidates: [getListGamesInfiniteQueryKey(), ...JOB_LIST_KEYS],
      },
      onSuccess: (result) => {
        toast.success(`Added "${result.game.title}"`)
        if (result.identify_job_id) {
          void watchIdentification(result.identify_job_id, result.game.id)
        }
        navigate({ to: "/games/$gameId", params: { gameId: result.game.id } })
      },
    },
  })
  const cancelMutation = useCancelUpload({ mutation: { meta: { errorToast: false } } })

  const form = useAppForm({
    defaultValues: {
      title: "",
      slug: stage.suggested_slug,
      library_id: libraries[0]?.id ?? "",
      kind: stage.suggested_kind as string,
    },
    validators: {
      onSubmit: z.object({
        title: z.string().trim().min(1, "Required"),
        slug: z
          .string()
          .trim()
          .min(1, "Required")
          .max(SLUG_MAX_LENGTH, "Too long")
          .regex(SLUG_PATTERN, "Lowercase, hyphen-separated"),
        library_id: z.string().min(1, "Required"),
        kind: z.string().min(1, "Required"),
      }),
    },
    onSubmit: async ({ value }) => {
      try {
        // Awaited so isSubmitting holds the button through the request —
        // a second click would re-POST the already-consumed stage.
        await finalizeMutation.mutateAsync({
          data: {
            stage_id: stage.stage_id,
            library_id: value.library_id,
            slug: value.slug.trim(),
            title: value.title.trim(),
            kind: value.kind as ArtifactKind,
            chosen_signature_id: chosen?.signature_id ?? null,
          },
        })
      } catch {
        // The global MutationCache onError already toasted.
      }
    },
  })

  const choose = (match: SignatureMatchOut) => {
    const next = chosen?.signature_id === match.signature_id ? null : match
    setChosen(next)
    if (next) {
      const title = cleanDatName(next.game_name)
      form.setFieldValue("title", title)
      form.setFieldValue("slug", slugify(title))
    }
  }

  const handleCancel = () => {
    // Best-effort staging cleanup; a failed cancel leaves the stage rescuable.
    cancelMutation.mutate({ stageId: stage.stage_id })
    onReset()
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        form.handleSubmit()
      }}
      className="max-w-xl space-y-4"
    >
      <FileSummary stage={stage} />
      <MatchesPanel matches={stage.matches} chosen={chosen} onChoose={choose} />

      <form.AppField name="title">
        {(f) => <f.TextField label="Title" placeholder="Doom II" />}
      </form.AppField>
      <form.AppField name="slug">
        {(f) => (
          <f.TextField label="Slug" description="URL identifier. Lowercase, hyphen-separated." />
        )}
      </form.AppField>
      <form.AppField name="library_id">
        {(f) => (
          <f.SelectField
            label="Library"
            options={libraries.map((library) => ({ value: library.id, label: library.name }))}
            clearable={false}
          />
        )}
      </form.AppField>
      {libraries.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No libraries yet —{" "}
          <Link to="/settings" search={{ tab: "libraries" }} className="underline">
            create one in Settings
          </Link>{" "}
          first.
        </p>
      )}
      <form.AppField name="kind">
        {(f) => <f.SelectField label="Kind" options={KIND_OPTIONS} clearable={false} />}
      </form.AppField>

      <div className="flex items-center gap-2 pt-2">
        <form.AppForm>
          <form.SubmitButton>Add to library</form.SubmitButton>
        </form.AppForm>
        <Button type="button" variant="outline" onClick={handleCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function MatchesPanel({
  matches,
  chosen,
  onChoose,
}: {
  matches: SignatureMatchOut[]
  chosen: SignatureMatchOut | null
  onChoose: (match: SignatureMatchOut) => void
}) {
  if (matches.length === 0) return null
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium">Identified by hash</p>
      <p className="text-sm text-muted-foreground">
        Choosing a match prefills the form and links metadata automatically after the upload.
      </p>
      <div className="divide-y rounded-md border">
        {matches.map((match) => {
          const selected = chosen?.signature_id === match.signature_id
          return (
            <button
              key={match.signature_id}
              type="button"
              onClick={() => onChoose(match)}
              aria-pressed={selected}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50",
                selected && "bg-muted/50",
              )}
            >
              <CheckCircleIcon
                weight={selected ? "fill" : "regular"}
                className={selected ? "text-primary" : "text-muted-foreground/50"}
              />
              <span className="truncate">{match.game_name}</span>
              <Badge variant="outline" className="ml-auto shrink-0">
                {match.source_slug} · {match.dataset_name}
              </Badge>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function FileSummary({ stage }: { stage: StageOut }) {
  return (
    <div className="flex items-center gap-3 rounded-md border bg-muted/50 p-3">
      <FileIcon className="size-5 text-muted-foreground" weight="duotone" />
      <span className="flex-1 truncate font-mono text-sm">{stage.filename}</span>
      <span className="text-xs text-muted-foreground tabular-nums">{formatSize(stage.size)}</span>
    </div>
  )
}
