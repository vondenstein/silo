import { Badge } from "@/components/ui/badge"
import type { GameDetail, RatingEntry } from "@/lib/api/model"
import { GameControllerIcon } from "@phosphor-icons/react"
import { DangerActions } from "@/routes/games/-components/danger-actions"
import { GAME_TYPE_OPTIONS, WRAPPER_OPTIONS, optionLabel } from "@/routes/games/-components/labels"
import { Fragment, useState } from "react"

export function Hero({ game }: { game: GameDetail }) {
  return (
    <div className="flex flex-col gap-6 md:flex-row">
      {/* Keyed by src so the failed latch resets when the cover changes. */}
      <Cover key={game.cover_url} src={game.cover_url ?? null} alt={game.title} />
      <div className="flex-1 space-y-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{game.title}</h1>
          {game.first_release_date && (
            <p className="mt-1 text-sm text-muted-foreground">
              {game.first_release_date.slice(0, 4)}
            </p>
          )}
        </div>
        <BadgeRow game={game} />
        <InfoGrid game={game} />
        <DangerActions gameId={game.id} libraryId={game.library_id} title={game.title} />
      </div>
    </div>
  )
}

function Cover({ src, alt }: { src: string | null; alt: string }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return (
      <div className="flex aspect-[3/4] h-80 shrink-0 items-center justify-center self-start rounded-lg bg-linear-to-br from-muted to-muted-foreground/15">
        <GameControllerIcon className="size-16 opacity-80" weight="duotone" />
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={alt}
      className="aspect-[3/4] h-80 shrink-0 self-start rounded-lg object-cover"
      onError={() => setFailed(true)}
    />
  )
}

// Display preference when several authorities rate the same game.
const RATING_ORDER = ["esrb", "pegi", "usk", "classind", "acb", "grac", "cero", "csrr", "igrs"]

function pickRating(ratings: RatingEntry[]): RatingEntry | null {
  for (const authority of RATING_ORDER) {
    const match = ratings.find((rating) => rating.authority === authority)
    if (match) return match
  }
  return ratings[0] ?? null
}

function BadgeRow({ game }: { game: GameDetail }) {
  const rating = pickRating(game.ratings)
  if (!game.game_type && !game.wrapper && !rating && !game.genres.length && !game.themes.length) {
    return null
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {game.game_type && (
        <Badge variant="outline">{optionLabel(GAME_TYPE_OPTIONS, game.game_type)}</Badge>
      )}
      {game.wrapper && (
        <Badge variant="secondary">{optionLabel(WRAPPER_OPTIONS, game.wrapper)}</Badge>
      )}
      {rating && (
        <Badge variant="outline">
          {rating.authority.toUpperCase()} {rating.value}
        </Badge>
      )}
      {game.genres.map((genre) => (
        <Badge key={genre.slug} variant="secondary">
          {genre.name}
        </Badge>
      ))}
      {game.themes.map((theme) => (
        <Badge key={theme.slug} variant="outline" className="text-muted-foreground">
          {theme.name}
        </Badge>
      ))}
    </div>
  )
}

function InfoGrid({ game }: { game: GameDetail }) {
  const names = (entities: { name: string }[]) => entities.map((entity) => entity.name).join(", ")
  const rows: [string, string][] = [
    [game.developers.length > 1 ? "Developers" : "Developer", names(game.developers)],
    [game.publishers.length > 1 ? "Publishers" : "Publisher", names(game.publishers)],
    ["Series", names(game.series)],
    ["Platforms", names(game.platforms)],
  ]
  const filled = rows.filter(([, value]) => value)
  if (filled.length === 0) return null
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
      {filled.map(([label, value]) => (
        <Fragment key={label}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd>{value}</dd>
        </Fragment>
      ))}
    </dl>
  )
}
