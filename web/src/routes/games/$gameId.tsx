import { Button } from "@/components/ui/button"
import { useActiveJobs } from "@/hooks/use-active-jobs"
import { getGetGameSuspenseQueryOptions, useGetGameSuspense } from "@/lib/api/client"
import { JobKind } from "@/lib/api/model"
import { libraryListQueryOptions } from "@/lib/queries"
import { ArrowLeftIcon } from "@phosphor-icons/react"
import { Link, createFileRoute } from "@tanstack/react-router"
import { EditGameDialog } from "@/routes/games/-components/edit-game-dialog"
import { FetchMetadataButton } from "@/routes/games/-components/fetch-metadata-button"
import { Hero } from "@/routes/games/-components/hero"
import { FilesTable } from "@/routes/games/-components/files-table"
import { ReadManualButton } from "@/routes/games/-components/read-manual-button"
import { ScreenshotGallery } from "@/routes/games/-components/screenshot-gallery"

export const Route = createFileRoute("/games/$gameId")({
  loader: ({ context: { queryClient }, params: { gameId } }) =>
    Promise.all([
      queryClient.ensureQueryData(getGetGameSuspenseQueryOptions(gameId)),
      // The edit dialog's Library select reads this suspensefully.
      queryClient.ensureInfiniteQueryData(libraryListQueryOptions()),
    ]),
  component: RouteComponent,
  staticData: {
    title: "Game",
  },
})

function RouteComponent() {
  const { gameId } = Route.useParams()
  // gog_import is the only post-creation writer of artifact statuses, so the
  // incomplete-artifacts poll runs only while an import is active (a stuck
  // missing/partial game must not poll forever).
  const importing = useActiveJobs(JobKind.gog_import).length > 0
  const { data: game } = useGetGameSuspense(gameId, {
    query: {
      // Live file statuses while an import is filling the manifest.
      refetchInterval: (query) =>
        importing && query.state.data?.artifacts.some((artifact) => artifact.status !== "stored")
          ? 3000
          : false,
    },
  })
  const description = game.description_full ?? game.description_short

  return (
    <div className="space-y-8 px-4 pb-12 lg:px-6">
      <div className="flex justify-between">
        <BackLink libraryId={game.library_id} />
        <div className="flex gap-2">
          <ReadManualButton game={game} />
          {game.external_identities.length > 0 && <FetchMetadataButton gameId={game.id} />}
          <EditGameDialog game={game} />
        </div>
      </div>
      <Hero game={game} />
      {description && <Description html={description} />}
      <ScreenshotGallery urls={game.assets.screenshots} title={game.title} />
      <FilesTable artifacts={game.artifacts} />
    </div>
  )
}

function BackLink({ libraryId }: { libraryId: string }) {
  return (
    <Button variant="ghost" size="sm" className="-ml-2 w-fit" asChild>
      <Link to="/libraries/$libraryId" params={{ libraryId }}>
        <ArrowLeftIcon /> Back to library
      </Link>
    </Button>
  )
}

function Description({ html }: { html: string }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">About</h2>
      <div
        className="max-w-3xl text-sm leading-relaxed text-foreground/90 [&_a]:text-primary [&_a]:underline [&_h3]:mt-4 [&_h3]:mb-2 [&_h3]:font-semibold [&_h4]:mt-3 [&_h4]:mb-1 [&_h4]:font-semibold [&_li]:my-1 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-3 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </section>
  )
}
