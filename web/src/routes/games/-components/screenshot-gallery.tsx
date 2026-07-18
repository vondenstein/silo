import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { CaretLeftIcon, CaretRightIcon } from "@phosphor-icons/react"
import { useState } from "react"

export function ScreenshotGallery({ urls, title }: { urls: string[]; title: string }) {
  const [index, setIndex] = useState<number | null>(null)
  if (urls.length === 0) return null
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight">Screenshots</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {urls.map((url, i) => (
          <button
            key={url}
            type="button"
            onClick={() => setIndex(i)}
            className="overflow-hidden rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <img
              src={url}
              alt={`${title} screenshot ${i + 1}`}
              loading="lazy"
              className="aspect-video w-full object-cover"
            />
          </button>
        ))}
      </div>
      <Lightbox urls={urls} title={title} index={index} onIndexChange={setIndex} />
    </section>
  )
}

function Lightbox({
  urls,
  title,
  index,
  onIndexChange,
}: {
  urls: string[]
  title: string
  index: number | null
  onIndexChange: (index: number | null) => void
}) {
  const count = urls.length
  const step = (delta: number) => {
    if (index === null) return
    onIndexChange((index + delta + count) % count)
  }
  return (
    <Dialog open={index !== null} onOpenChange={(open) => !open && onIndexChange(null)}>
      <DialogContent
        className="border-none bg-transparent p-0 shadow-none sm:max-w-[92vw]"
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") step(1)
          if (e.key === "ArrowLeft") step(-1)
        }}
      >
        <DialogTitle className="sr-only">{title} screenshots</DialogTitle>
        <DialogDescription className="sr-only">
          Use the arrow keys to move between screenshots.
        </DialogDescription>
        {index !== null && urls[index] !== undefined && (
          <img
            src={urls[index]}
            alt={`${title} screenshot ${index + 1}`}
            className="mx-auto max-h-[82vh] rounded-lg object-contain"
          />
        )}
        <div className="flex items-center justify-center gap-4 pb-2">
          <Button
            variant="secondary"
            size="icon"
            onClick={() => step(-1)}
            aria-label="Previous screenshot"
          >
            <CaretLeftIcon />
          </Button>
          <span className="text-sm text-white/80 tabular-nums">
            {index !== null ? index + 1 : 0} / {count}
          </span>
          <Button
            variant="secondary"
            size="icon"
            onClick={() => step(1)}
            aria-label="Next screenshot"
          >
            <CaretRightIcon />
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
