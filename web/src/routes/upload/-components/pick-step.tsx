import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { CloudArrowUpIcon } from "@phosphor-icons/react"
import { useRef, useState } from "react"

export function PickStep({ onPick }: { onPick: (file: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        const file = e.dataTransfer.files[0]
        if (file) onPick(file)
      }}
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed py-16 transition-colors",
        dragOver ? "border-primary bg-primary/5" : "border-border hover:bg-muted/30",
      )}
    >
      <CloudArrowUpIcon className="size-12 text-muted-foreground" weight="duotone" />
      <p className="text-sm text-muted-foreground">Drop a file here, or</p>
      <Button onClick={() => inputRef.current?.click()}>Choose file</Button>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onPick(file)
          e.target.value = ""
        }}
      />
    </div>
  )
}
