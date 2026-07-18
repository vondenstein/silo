import { GameList } from "@/components/game-list"
import { gameListQueryOptions } from "@/lib/queries"
import { createFileRoute } from "@tanstack/react-router"

export const Route = createFileRoute("/libraries/$libraryId")({
  loader: ({ context: { queryClient }, params: { libraryId } }) =>
    queryClient.ensureInfiniteQueryData(gameListQueryOptions({ library_id: libraryId })),
  component: RouteComponent,
  staticData: {
    title: "Libraries",
  },
})

function RouteComponent() {
  const { libraryId } = Route.useParams()
  return <GameList params={{ library_id: libraryId }} />
}
