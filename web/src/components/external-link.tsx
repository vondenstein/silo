import type { ReactNode } from "react"
import { ArrowUpRightIcon } from "@phosphor-icons/react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string
  children: ReactNode
  className?: string
}) {
  return (
    <Button variant="link" className={cn("gap-0 px-0.5", className)} asChild>
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
        <ArrowUpRightIcon weight="bold" />
      </a>
    </Button>
  )
}
