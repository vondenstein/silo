import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { getListFileContentsQueryOptions } from "@/lib/api/client"
import type { ArtifactOut, FileOut, GameDetail } from "@/lib/api/model"
import { pickPrimary, type ManualDoc } from "@/routes/games/-components/manual-match"
import { BookOpenIcon, CaretDownIcon } from "@phosphor-icons/react"
import { useQueries } from "@tanstack/react-query"
import { useRef } from "react"

type StoredFile = FileOut & { blake3: string; relative_path: string }

function isPdf(path: string): boolean {
  return path.toLowerCase().endsWith(".pdf")
}

function basename(path: string): string {
  return path.split("/").pop() ?? path
}

function memberUrl(fileId: string, member: string): string {
  const encoded = member.split("/").map(encodeURIComponent).join("/")
  return `/api/v1/files/${fileId}/contents/${encoded}?inline=true`
}

export function ReadManualButton({ game }: { game: GameDetail }) {
  const pointerClose = useRef(false)
  const artifacts = game.artifacts.filter((artifact) => artifact.kind === "manual")
  const stored = (artifact: ArtifactOut) =>
    artifact.files.filter(
      (file): file is StoredFile => file.blake3 != null && file.relative_path != null,
    )
  const zips = artifacts
    .flatMap(stored)
    .filter((file) => file.relative_path.toLowerCase().endsWith(".zip"))

  const contents = useQueries({
    queries: zips.map((file) => getListFileContentsQueryOptions(file.id)),
  })
  const membersByFile = new Map(
    zips.map((file, index) => [file.id, contents[index].data ?? []] as const),
  )

  const docs: ManualDoc[] = artifacts.flatMap((artifact) => {
    const artifactName = artifact.name ?? ""
    return stored(artifact).flatMap((file) => {
      if (isPdf(file.relative_path)) {
        return [
          {
            label: basename(file.relative_path).replace(/\.pdf$/i, ""),
            url: `/api/v1/files/${file.id}?inline=true`,
            artifactName,
          },
        ]
      }
      return (membersByFile.get(file.id) ?? [])
        .filter((member) => isPdf(member.path))
        .map((member) => ({
          label: basename(member.path).replace(/\.pdf$/i, ""),
          url: memberUrl(file.id, member.path),
          artifactName,
        }))
    })
  })

  if (docs.length === 0) return null
  const primary = pickPrimary(docs, game)
  if (docs.length === 1) {
    return <ManualLink href={primary.url} />
  }

  const groupNames = [...new Set(docs.map((doc) => doc.artifactName))]
  return (
    <div className="flex">
      <ManualLink href={primary.url} className="rounded-r-none" />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="icon"
            className="rounded-l-none border-l-0"
            aria-label="All manuals"
          >
            <CaretDownIcon />
          </Button>
        </DropdownMenuTrigger>
        {/* Pointer closes skip the focus restore (the trigger's ring would stay
            lit until the next click); keyboard closes keep it — Escape must
            return focus to the trigger. */}
        <DropdownMenuContent
          align="end"
          onPointerDown={() => {
            pointerClose.current = true
          }}
          onPointerDownOutside={() => {
            pointerClose.current = true
          }}
          onCloseAutoFocus={(e) => {
            if (pointerClose.current) e.preventDefault()
            pointerClose.current = false
          }}
        >
          {groupNames.map((groupName) => (
            <div key={groupName}>
              {groupNames.length > 1 && (
                <DropdownMenuLabel className="capitalize">{groupName}</DropdownMenuLabel>
              )}
              {docs
                .filter((doc) => doc.artifactName === groupName)
                .map((doc) => (
                  <DropdownMenuItem key={doc.url} asChild>
                    <a href={doc.url} target="_blank" rel="noreferrer">
                      {doc.label}
                    </a>
                  </DropdownMenuItem>
                ))}
            </div>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function ManualLink({ href, className }: { href: string; className?: string }) {
  return (
    <Button variant="outline" className={className} asChild>
      <a href={href} target="_blank" rel="noreferrer">
        <BookOpenIcon /> Read manual
      </a>
    </Button>
  )
}
