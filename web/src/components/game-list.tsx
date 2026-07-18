import { useSuspenseInfiniteQuery } from "@tanstack/react-query"

import { GameCards } from "@/components/game-cards"
import { LoadMoreButton } from "@/components/load-more-button"
import { gameListQueryOptions } from "@/lib/queries"
import type { ListGamesParams } from "@/lib/api/model"

export function GameList({ params }: { params?: ListGamesParams }) {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useSuspenseInfiniteQuery(
    gameListQueryOptions(params),
  )
  const games = data.pages.flatMap((page) => page.items)

  if (games.length === 0) {
    return (
      <p className="px-4 text-sm text-muted-foreground lg:px-6">
        No games yet — upload a file or import from GOG to get started.
      </p>
    )
  }
  return (
    <>
      <GameCards games={games} />
      {hasNextPage && (
        <div className="flex justify-center">
          <LoadMoreButton isFetchingNextPage={isFetchingNextPage} onClick={() => fetchNextPage()} />
        </div>
      )}
    </>
  )
}
