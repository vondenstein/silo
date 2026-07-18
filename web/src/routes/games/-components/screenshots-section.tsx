import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { Button } from "@/components/ui/button"
import { AssetKind, FieldKey } from "@/lib/api/model"
import type { AssetCandidateOut, GameDetail } from "@/lib/api/model"
import { AssetCard } from "@/routes/games/-components/asset-card"
import {
  AssetSectionFrame,
  AssetUploadButton,
  SectionNote,
} from "@/routes/games/-components/asset-section"
import { useEditSection } from "@/routes/games/-components/edit-session"
import { LockToggle } from "@/routes/games/-components/lock-toggle"
import { SectionHeader } from "@/routes/games/-components/section-header"
import { EyeIcon, EyeSlashIcon } from "@phosphor-icons/react"
import { useState } from "react"
import type { ReactNode } from "react"

export function ScreenshotsSection({ game }: { game: GameDetail }) {
  return (
    <AssetSectionFrame gameId={game.id} errorText="Failed to load screenshots.">
      {(candidates) => <ScreenshotsEditor game={game} candidates={candidates.screenshot} />}
    </AssetSectionFrame>
  )
}

function ScreenshotsEditor({
  game,
  candidates,
}: {
  game: GameDetail
  candidates: AssetCandidateOut[]
}) {
  // Baseline pinned at mount — see details-section; the shell remounts to re-baseline.
  const [initialVisible] = useState<string[]>(() =>
    candidates
      .filter((c) => c.visible)
      .toSorted((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0))
      .map((c) => c.blake3),
  )
  const [visible, setVisible] = useState(initialVisible)

  const dirty =
    visible.length !== initialVisible.length ||
    visible.some((blake3, i) => blake3 !== initialVisible[i])
  const session = useEditSection("screenshots", { dirty }, () =>
    dirty ? { assetPut: { kind: AssetKind.screenshot, blobs: visible } } : null,
  )

  const byBlake = new Map(candidates.map((c) => [c.blake3, c]))
  const shown = visible.flatMap((blake3) => byBlake.get(blake3) ?? [])
  const hidden = candidates.filter((c) => !visible.includes(c.blake3))

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  // Every change auto-flips the lock on; the user can still flip it back before save.
  const hide = (blake3: string) => {
    setVisible((current) => current.filter((b) => b !== blake3))
    session.lockOnChange(FieldKey.screenshot)
  }
  const show = (blake3: string) => {
    setVisible((current) => [...current, blake3])
    session.lockOnChange(FieldKey.screenshot)
  }
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (over === null || active.id === over.id) return
    setVisible((current) =>
      arrayMove(current, current.indexOf(String(active.id)), current.indexOf(String(over.id))),
    )
    session.lockOnChange(FieldKey.screenshot)
  }

  return (
    <div className="flex flex-1 flex-col gap-4">
      <SectionHeader
        title="Screenshots"
        description="Drag to reorder; hide the ones you don't want in the gallery. Locking keeps your arrangement through metadata fetches."
        action={
          <LockToggle
            locked={session.locks.has(FieldKey.screenshot)}
            onToggle={() => session.toggleLock(FieldKey.screenshot)}
          />
        }
      />
      {candidates.length === 0 ? (
        <SectionNote>No screenshots yet — fetch metadata first.</SectionNote>
      ) : (
        <>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={visible} strategy={rectSortingStrategy}>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {shown.map((candidate) => (
                  <SortableShot
                    key={candidate.blake3}
                    candidate={candidate}
                    onHide={() => hide(candidate.blake3)}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
          {hidden.length > 0 && (
            <>
              <h4 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Hidden
              </h4>
              <div className="grid grid-cols-2 gap-3 opacity-70 sm:grid-cols-3">
                {hidden.map((candidate) => (
                  <AssetCard
                    key={candidate.blake3}
                    candidate={candidate}
                    aspect="video"
                    action={
                      <ShotAction
                        label="Show screenshot"
                        onClick={() => show(candidate.blake3)}
                        icon={<EyeIcon />}
                      />
                    }
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}
      <AssetUploadButton
        gameId={game.id}
        kind={AssetKind.screenshot}
        multiple
        onUploaded={(candidate) => {
          setVisible((current) =>
            current.includes(candidate.blake3) ? current : [...current, candidate.blake3],
          )
          session.lockOnChange(FieldKey.screenshot)
        }}
      />
    </div>
  )
}

function SortableShot({ candidate, onHide }: { candidate: AssetCandidateOut; onHide: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: candidate.blake3,
  })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={isDragging ? "z-10 cursor-grabbing opacity-80" : "cursor-grab touch-none"}
      {...attributes}
      {...listeners}
    >
      <AssetCard
        candidate={candidate}
        aspect="video"
        action={<ShotAction label="Hide screenshot" onClick={onHide} icon={<EyeSlashIcon />} />}
      />
    </div>
  )
}

function ShotAction({
  label,
  onClick,
  icon,
}: {
  label: string
  onClick: () => void
  icon: ReactNode
}) {
  return (
    <Button
      type="button"
      variant="secondary"
      size="icon"
      className="size-6"
      onClick={onClick}
      aria-label={label}
    >
      {icon}
    </Button>
  )
}
