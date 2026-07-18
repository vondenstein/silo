import type { FieldKey } from "@/lib/api/model"
import { LockToggle } from "@/routes/games/-components/lock-toggle"
import type { ReactNode } from "react"

export function FieldRow({
  fieldKey,
  locks,
  onToggle,
  children,
}: {
  fieldKey: FieldKey
  locks: ReadonlySet<FieldKey>
  onToggle: (key: FieldKey) => void
  children: ReactNode
}) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-end gap-1">
      {children}
      <LockToggle locked={locks.has(fieldKey)} onToggle={() => onToggle(fieldKey)} />
    </div>
  )
}
