import { useRef } from "react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { getGetGameAssetsQueryKey, useGetGameAssets, useUploadGameAsset } from "@/lib/api/client"
import type { AssetCandidateOut, AssetKind, GameAssetCandidates } from "@/lib/api/model"
import { queryClient } from "@/lib/query-client"
import { UploadSimpleIcon } from "@phosphor-icons/react"

export function SectionNote({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}

/** Fetches the candidate pool and renders the section only once it's available. */
export function AssetSectionFrame({
  gameId,
  errorText,
  children,
}: {
  gameId: string
  errorText: string
  children: (candidates: GameAssetCandidates) => ReactNode
}) {
  const { data: candidates, isPending, isError } = useGetGameAssets(gameId)
  if (isPending || isError) return <SectionNote>{isError ? errorText : "Loading…"}</SectionNote>
  return <>{children(candidates)}</>
}

export function AssetUploadButton({
  gameId,
  kind,
  multiple = false,
  onUploaded,
}: {
  gameId: string
  kind: AssetKind
  multiple?: boolean
  onUploaded: (candidate: AssetCandidateOut) => void
}) {
  const upload = useUploadGameAsset({
    mutation: { meta: { errorToast: "Failed to upload image" } },
  })
  const fileInput = useRef<HTMLInputElement>(null)

  const onChange = async (files: FileList | null) => {
    if (!files?.length) return
    try {
      // Uploads land staged (not visible); onUploaded adds each to the section's
      // draft, and the shell's Save publishes them via the curation PUT.
      for (const file of files) {
        onUploaded(await upload.mutateAsync({ gameId, kind, data: { file } }))
      }
    } catch {
      // The global MutationCache onError already toasted; earlier files in the
      // batch may have uploaded.
    } finally {
      await queryClient.invalidateQueries({ queryKey: getGetGameAssetsQueryKey(gameId) })
      if (fileInput.current) fileInput.current.value = ""
    }
  }

  return (
    <div className="mt-auto">
      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        multiple={multiple}
        hidden
        onChange={(e) => onChange(e.target.files)}
      />
      <Button
        type="button"
        variant="outline"
        onClick={() => fileInput.current?.click()}
        disabled={upload.isPending}
      >
        <UploadSimpleIcon />{" "}
        {upload.isPending ? "Uploading…" : multiple ? "Upload images" : "Upload image"}
      </Button>
    </div>
  )
}
