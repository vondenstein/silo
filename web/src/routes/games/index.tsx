import { GameList } from "@/components/game-list"
import { gameListQueryOptions } from "@/lib/queries"
import { createFileRoute } from "@tanstack/react-router"

export const Route = createFileRoute("/games/")({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureInfiniteQueryData(gameListQueryOptions()),
  component: RouteComponent,
  staticData: {
    title: "Games",
  },
})

function RouteComponent() {
  return <GameList />
}
