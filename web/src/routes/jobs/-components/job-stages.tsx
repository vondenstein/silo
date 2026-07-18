import { Progress } from "@/components/ui/progress"
import type { JobStage, JobStageStatus } from "@/lib/api/model"
import { formatSize } from "@/lib/format-size"
import { cn } from "@/lib/utils"
import {
  CheckCircleIcon,
  CircleIcon,
  SpinnerGapIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react"

// The schema defaults `status`, so the generated field is optional; the wire always carries it.
export function stageStatus(stage: JobStage): JobStageStatus {
  return stage.status ?? "pending"
}

type StageGroup = { group: string; stages: JobStage[] }

function stageGroups(stages: JobStage[]): StageGroup[] {
  const groups: StageGroup[] = []
  for (const stage of stages) {
    const group = stage.group ?? "Steps"
    const last = groups[groups.length - 1]
    if (last && last.group === group) last.stages.push(stage)
    else groups.push({ group, stages: [stage] })
  }
  return groups
}

export function JobStages({ stages }: { stages: JobStage[] }) {
  return (
    <div className="space-y-3 py-3 pr-4 pl-11 whitespace-normal">
      {stageGroups(stages).map((section) => (
        <div key={section.group}>
          <div className="pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {section.group}
          </div>
          <div className="divide-y">
            {section.stages.map((stage) => (
              <div key={stage.key} className="flex items-center gap-2 py-1.5">
                <StageIcon status={stageStatus(stage)} />
                <span
                  title={stage.label}
                  className={cn(
                    "w-84 shrink-0 truncate text-sm",
                    stageStatus(stage) === "pending" && "text-muted-foreground",
                  )}
                >
                  {stage.label}
                </span>
                <div className="min-w-0 flex-1">
                  <StageProgress stage={stage} />
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function StageProgress({ stage }: { stage: JobStage }) {
  if (stage.error) {
    return <span className="text-xs text-destructive">{stage.error}</span>
  }
  if (stageStatus(stage) === "running" && stage.bytes_total != null && stage.bytes_done != null) {
    return (
      <div className="flex items-center gap-3">
        <Progress
          value={Math.min(100, (stage.bytes_done / stage.bytes_total) * 100)}
          className="flex-1"
        />
        <span className="w-40 shrink-0 text-xs whitespace-nowrap text-muted-foreground">
          {formatSize(stage.bytes_done)} / {formatSize(stage.bytes_total)}
        </span>
      </div>
    )
  }
  const downloaded =
    stageStatus(stage) === "completed" ? (stage.bytes_done ?? stage.bytes_total) : null
  if (downloaded == null) return null
  return (
    <div className="flex items-center gap-3">
      <Progress value={100} className="flex-1" />
      <span className="w-40 shrink-0 text-xs whitespace-nowrap text-muted-foreground">
        {formatSize(downloaded)}
      </span>
    </div>
  )
}

function StageIcon({ status }: { status: JobStageStatus }) {
  if (status === "completed") {
    return (
      <CheckCircleIcon
        className="size-4 shrink-0 text-green-600 dark:text-green-400"
        weight="fill"
      />
    )
  }
  if (status === "running") {
    return <SpinnerGapIcon className="size-4 shrink-0 animate-spin" />
  }
  if (status === "failed") {
    return <WarningCircleIcon className="size-4 shrink-0 text-destructive" weight="fill" />
  }
  return <CircleIcon className="size-4 shrink-0 text-muted-foreground/40" />
}
