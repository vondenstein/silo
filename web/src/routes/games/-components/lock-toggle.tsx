import { Button } from "@/components/ui/button"
import { LockSimpleIcon, LockSimpleOpenIcon } from "@phosphor-icons/react"

export function LockToggle({ locked, onToggle }: { locked: boolean; onToggle: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onToggle}
      aria-label={locked ? "Unlock field" : "Lock field"}
      aria-pressed={locked}
      className={locked ? undefined : "text-muted-foreground/50"}
    >
      {locked ? <LockSimpleIcon weight="fill" /> : <LockSimpleOpenIcon />}
    </Button>
  )
}
