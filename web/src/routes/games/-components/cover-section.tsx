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
import { useState } from "react"

export function CoverSection({ game }: { game: GameDetail }) {
  return (
    <AssetSectionFrame gameId={game.id} errorText="Failed to load covers.">
      {(candidates) => <CoverPicker game={game} candidates={candidates.cover} />}
    </AssetSectionFrame>
  )
}

function CoverPicker({ game, candidates }: { game: GameDetail; candidates: AssetCandidateOut[] }) {
  // Baseline pinned at mount — see details-section; the shell remounts to re-baseline.
  const [initialSelected] = useState<string | null>(
    () =>
      candidates.filter((c) => c.visible).toSorted((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0))[0]
        ?.blake3 ?? null,
  )
  const [selected, setSelected] = useState(initialSelected)

  const dirty = selected !== initialSelected
  const session = useEditSection("cover", { dirty }, () =>
    dirty
      ? { assetPut: { kind: AssetKind.cover, blobs: selected === null ? [] : [selected] } }
      : null,
  )

  const pick = (blake3: string) => {
    setSelected((current) => (current === blake3 ? null : blake3))
    session.lockOnChange(FieldKey.cover)
  }

  return (
    <div className="flex flex-1 flex-col gap-4">
      <SectionHeader
        title="Cover"
        description="The cover shown on cards and the game page. Locking keeps your pick through metadata fetches."
        action={
          <LockToggle
            locked={session.locks.has(FieldKey.cover)}
            onToggle={() => session.toggleLock(FieldKey.cover)}
          />
        }
      />
      {candidates.length === 0 ? (
        <SectionNote>No covers yet — fetch metadata first.</SectionNote>
      ) : (
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
          {candidates.map((candidate) => (
            <AssetCard
              key={candidate.blake3}
              candidate={candidate}
              aspect="portrait"
              selected={candidate.blake3 === selected}
              onClick={() => pick(candidate.blake3)}
            />
          ))}
        </div>
      )}
      <AssetUploadButton
        gameId={game.id}
        kind={AssetKind.cover}
        onUploaded={(candidate) => {
          setSelected(candidate.blake3)
          session.lockOnChange(FieldKey.cover)
        }}
      />
    </div>
  )
}
