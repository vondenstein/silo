import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { FileIcon } from "@phosphor-icons/react"

export function UploadingStep({
  filename,
  progress,
  onCancel,
}: {
  filename: string
  progress: number
  onCancel: () => void
}) {
  return (
    <div className="space-y-3 rounded-lg border p-6">
      <div className="flex items-center gap-3">
        <FileIcon className="size-5 text-muted-foreground" weight="duotone" />
        <span className="flex-1 truncate font-mono text-sm">{filename}</span>
        <span className="text-sm text-muted-foreground tabular-nums">{progress}%</span>
      </div>
      <Progress value={progress} />
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Uploading and hashing…</p>
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
