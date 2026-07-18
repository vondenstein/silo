import { GameCard, GameGrid } from "@/components/game-cards"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useActiveJobs } from "@/hooks/use-active-jobs"
import {
  getGetGogLibraryQueryKey,
  getListGamesInfiniteQueryKey,
  useImportGogGame,
  useGetGogLibrary,
} from "@/lib/api/client"
import { JobKind } from "@/lib/api/model"
import { ApiError } from "@/lib/fetch-mutator"
import { JOB_LIST_KEYS, libraryListQueryOptions } from "@/lib/queries"
import { queryClient } from "@/lib/query-client"
import { ArrowClockwiseIcon, CheckCircleIcon, SpinnerGapIcon } from "@phosphor-icons/react"
import { useSuspenseInfiniteQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useState } from "react"

function gogImageUrl(image_url: string | null): string | null {
  if (!image_url) return null
  const withScheme = image_url.startsWith("//") ? `https:${image_url}` : image_url
  // Bare CDN id → full-res `.jpg`. Sized variant (e.g. `_glx_logo_2x.jpg`) → strip suffix.
  if (/\.(jpg|png)$/i.test(withScheme))
    return withScheme.replace(/_[a-z0-9_]+\.(jpg|png)$/i, ".jpg")
  return `${withScheme}.jpg`
}

type ImportState = "idle" | "running" | "imported" | "incomplete"

function ImportButton({
  state,
  onImport,
  disabled = false,
}: {
  state: ImportState
  onImport: () => void
  disabled?: boolean
}) {
  if (state === "imported")
    return (
      <Button variant="outline" disabled className="w-full">
        <CheckCircleIcon weight="fill" />
        Imported
      </Button>
    )
  if (state === "running")
    return (
      <Button disabled variant="secondary" className="w-full">
        <SpinnerGapIcon className="animate-spin" />
        Importing…
      </Button>
    )
  if (state === "incomplete")
    return (
      <Button variant="secondary" className="w-full" onClick={onImport} disabled={disabled}>
        <ArrowClockwiseIcon />
        Resume
      </Button>
    )
  return (
    <Button variant="secondary" className="w-full" onClick={onImport} disabled={disabled}>
      Import
    </Button>
  )
}

export function GogLibrary() {
  // Deliberately a plain useQuery, not loader+suspense: the throttled multi-page
  // GOG fetch is slow, must not block navigation or fire on intent-preload, and
  // the 409-disconnected/502 states need in-page renders a route boundary can't give.
  const { data: gogGames = [], isLoading, error } = useGetGogLibrary()
  const { data: libraryPages } = useSuspenseInfiniteQuery(libraryListQueryOptions())
  const libraries = libraryPages.pages.flatMap((page) => page.items)
  const [libraryId, setLibraryId] = useState<string>()
  const targetLibrary = libraryId ?? libraries[0]?.id

  // When an active import finishes, refresh the imported flags + games list.
  const activeImports = useActiveJobs(JobKind.gog_import, () => {
    queryClient.invalidateQueries({ queryKey: getGetGogLibraryQueryKey() })
    queryClient.invalidateQueries({ queryKey: getListGamesInfiniteQueryKey() })
  })
  const importingIds = new Set(activeImports.map((job) => job.payload.gog_id as number))

  const importMutation = useImportGogGame({
    mutation: {
      meta: { errorToast: "Failed to start import", invalidates: JOB_LIST_KEYS },
    },
  })

  if (isLoading) {
    return <p className="px-4 text-sm text-muted-foreground lg:px-6">Loading library…</p>
  }
  if (error) {
    const msg = error instanceof ApiError ? error.message : "Couldn't load GOG library"
    return <p className="px-4 text-sm text-destructive lg:px-6">{msg}</p>
  }

  return (
    <div className="flex flex-col gap-4">
      <Field orientation="horizontal" className="max-w-md px-4 lg:px-6">
        <FieldLabel htmlFor="import-library">Import into</FieldLabel>
        <Select value={targetLibrary} onValueChange={setLibraryId}>
          <SelectTrigger id="import-library" className="w-48">
            <SelectValue placeholder="Select a library" />
          </SelectTrigger>
          <SelectContent>
            {libraries.map((library) => (
              <SelectItem key={library.id} value={library.id}>
                {library.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      {libraries.length === 0 && (
        <p className="px-4 text-sm text-muted-foreground lg:px-6">
          No libraries yet —{" "}
          <Link to="/settings" search={{ tab: "libraries" }} className="underline">
            create one in Settings
          </Link>{" "}
          first.
        </p>
      )}
      {gogGames.length === 0 && (
        <p className="px-4 text-sm text-muted-foreground lg:px-6">
          This GOG account owns no games.
        </p>
      )}
      <GameGrid>
        {gogGames.map((game) => {
          // An active job outranks the imported flag: the identity row (which
          // drives `imported`) is created before the downloads run.
          const running =
            importingIds.has(game.gog_id) ||
            (importMutation.isPending && importMutation.variables?.data.gog_id === game.gog_id)
          const state: ImportState = running
            ? "running"
            : game.imported && game.complete
              ? "imported"
              : game.imported
                ? "incomplete"
                : "idle"
          return (
            <GameCard
              key={game.gog_id}
              coverSrc={gogImageUrl(game.image_url)}
              title={game.title}
              action={
                <ImportButton
                  state={state}
                  disabled={!targetLibrary}
                  onImport={() =>
                    targetLibrary &&
                    importMutation.mutate({
                      data: { gog_id: game.gog_id, library_id: targetLibrary },
                    })
                  }
                />
              }
            />
          )
        })}
      </GameGrid>
    </div>
  )
}
