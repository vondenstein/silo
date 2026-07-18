import { Card, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import type { Game } from "@/lib/api/model"
import { GameControllerIcon } from "@phosphor-icons/react"
import { Link } from "@tanstack/react-router"
import { useState, type ReactNode } from "react"

function GameCover({ src, alt }: { src: string | null; alt: string }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed)
    return (
      <div className="flex aspect-video w-full items-center justify-center bg-linear-to-br from-muted to-muted-foreground/15">
        <GameControllerIcon className="size-12 opacity-80" weight="duotone" />
      </div>
    )
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      className="aspect-video w-full object-cover"
      onError={() => setFailed(true)}
    />
  )
}

export function GameCard({
  coverSrc,
  title,
  action,
  gameId,
}: {
  coverSrc: string | null
  title: string
  action?: ReactNode
  /** When set, the cover + title link to the game's detail page. */
  gameId?: string
}) {
  const titleNode = <CardTitle className="line-clamp-2 font-semibold">{title}</CardTitle>

  return (
    <Card className="gap-0 p-0 shadow-xs">
      {gameId ? (
        <Link
          to="/games/$gameId"
          params={{ gameId }}
          // ring-inset: the card's overflow-hidden would clip an outward ring.
          className="block focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none focus-visible:ring-inset"
          aria-label={title}
        >
          {/* Keyed by src so the failed latch resets when the cover changes. */}
          <GameCover key={coverSrc} src={coverSrc} alt={title} />
        </Link>
      ) : (
        <GameCover key={coverSrc} src={coverSrc} alt={title} />
      )}
      <CardHeader className="p-4">
        {gameId ? (
          <Link
            to="/games/$gameId"
            params={{ gameId }}
            className="rounded-xs hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            {titleNode}
          </Link>
        ) : (
          titleNode
        )}
      </CardHeader>
      {action && <CardFooter className="mt-auto p-4 pt-0">{action}</CardFooter>}
    </Card>
  )
}

export function GameGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-4 px-4 lg:px-6 @xl/main:grid-cols-3 @5xl/main:grid-cols-4">
      {children}
    </div>
  )
}

export function GameCards({ games }: { games: Game[] }) {
  return (
    <GameGrid>
      {games.map((game) => (
        <GameCard
          key={game.id}
          gameId={game.id}
          coverSrc={game.landscape_url ?? game.cover_url ?? null}
          title={game.title}
        />
      ))}
    </GameGrid>
  )
}
