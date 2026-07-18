import type { StageOut } from "@/lib/api/model"
import { libraryListQueryOptions } from "@/lib/queries"
import { createFileRoute } from "@tanstack/react-router"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { PickStep } from "@/routes/upload/-components/pick-step"
import { UploadingStep } from "@/routes/upload/-components/uploading-step"
import { FinalizeStep } from "@/routes/upload/-components/finalize-step"

type Mode =
  | { kind: "pick" }
  | { kind: "uploading"; filename: string; progress: number }
  | { kind: "ready"; stage: StageOut }

export const Route = createFileRoute("/upload/")({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureInfiniteQueryData(libraryListQueryOptions()),
  component: RouteComponent,
  staticData: {
    title: "Upload",
  },
})

function RouteComponent() {
  // Wizard state is deliberately ephemeral: refreshing mid-flow abandons the
  // stage (no rehydration endpoint); abandoned staging files wait for Epic C's GC.
  const [mode, setMode] = useState<Mode>({ kind: "pick" })
  const xhrRef = useRef<XMLHttpRequest | null>(null)

  const upload = (file: File) => {
    // XMLHttpRequest instead of fetch: upload progress events.
    const xhr = new XMLHttpRequest()
    xhrRef.current = xhr
    setMode({ kind: "uploading", filename: file.name, progress: 0 })
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        setMode({
          kind: "uploading",
          filename: file.name,
          progress: Math.round((e.loaded / e.total) * 100),
        })
      }
    })
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const stage: StageOut = JSON.parse(xhr.responseText)
        setMode({ kind: "ready", stage })
      } else {
        let detail = "Upload failed"
        try {
          const body = JSON.parse(xhr.responseText)
          if (typeof body?.detail === "string") detail = body.detail
        } catch {
          // response body isn't JSON — keep the default message
        }
        toast.error(detail)
        setMode({ kind: "pick" })
      }
    })
    xhr.addEventListener("error", () => {
      toast.error("Upload failed")
      setMode({ kind: "pick" })
    })
    // User-initiated cancel: no toast, back to the picker. No stage exists yet
    // (the response never arrived), so the partial staging file waits for GC.
    xhr.addEventListener("abort", () => setMode({ kind: "pick" }))

    const fd = new FormData()
    fd.append("file", file)
    xhr.open("POST", "/api/v1/upload/stage")
    xhr.send(fd)
  }

  return (
    <div className="flex flex-col gap-6 px-4 lg:px-6">
      {mode.kind === "pick" && <PickStep onPick={upload} />}
      {mode.kind === "uploading" && (
        <UploadingStep
          filename={mode.filename}
          progress={mode.progress}
          onCancel={() => xhrRef.current?.abort()}
        />
      )}
      {mode.kind === "ready" && (
        <FinalizeStep stage={mode.stage} onReset={() => setMode({ kind: "pick" })} />
      )}
    </div>
  )
}
