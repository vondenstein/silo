import type { ComponentProps } from "react"

import { Button } from "@/components/ui/button"

export function LoadMoreButton({
  isFetchingNextPage,
  onClick,
  size,
  className,
}: {
  isFetchingNextPage: boolean
  onClick: () => void
} & Pick<ComponentProps<typeof Button>, "size" | "className">) {
  return (
    <Button
      variant="outline"
      size={size}
      className={className}
      onClick={onClick}
      disabled={isFetchingNextPage}
    >
      {isFetchingNextPage ? "Loading…" : "Load more"}
    </Button>
  )
}
