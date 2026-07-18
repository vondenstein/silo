import { Badge } from "@/components/ui/badge"
import type { AssetCandidateOut } from "@/lib/api/model"
import { formatSize } from "@/lib/format-size"
import { cn } from "@/lib/utils"
import type { ReactNode } from "react"

export function AssetCard({
  candidate,
  aspect,
  selected = false,
  onClick,
  action,
}: {
  candidate: AssetCandidateOut
  aspect: "portrait" | "video"
  selected?: boolean
  onClick?: () => void
  action?: ReactNode
}) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md ring-offset-background",
        selected && "ring-2 ring-primary ring-offset-2",
      )}
    >
      <img
        src={candidate.url}
        alt=""
        loading="lazy"
        title={`${candidate.mime} · ${formatSize(candidate.size)}`}
        className={cn(
          "w-full object-cover",
          aspect === "portrait" ? "aspect-[3/4]" : "aspect-video",
        )}
      />
      {onClick && (
        <button
          type="button"
          onClick={onClick}
          aria-label={selected ? "Deselect" : "Select"}
          aria-pressed={selected}
          className="absolute inset-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        />
      )}
      {candidate.source_slugs.length > 0 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap gap-1 bg-linear-to-t from-black/70 to-transparent p-1.5 pt-4">
          {candidate.source_slugs.map((slug) => (
            <Badge key={slug} variant="secondary" className="px-1 py-0 text-[10px]">
              {slug}
            </Badge>
          ))}
        </div>
      )}
      {action && <div className="absolute top-1.5 right-1.5">{action}</div>}
    </div>
  )
}
