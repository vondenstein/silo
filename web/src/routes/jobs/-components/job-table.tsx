import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { Job, JobStage } from "@/lib/api/model"
import { relativeTime } from "@/lib/relative-time"
import { cn } from "@/lib/utils"
import { JobStages, stageStatus } from "@/routes/jobs/-components/job-stages"
import { CaretRightIcon } from "@phosphor-icons/react"
import { Fragment, useState } from "react"

const STATUS_BADGES: Record<Job["status"], string> = {
  pending: "",
  running: "border-blue-600/40 bg-blue-600/10 text-blue-700 dark:text-blue-400",
  completed: "border-green-600/40 bg-green-600/10 text-green-700 dark:text-green-400",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  interrupted: "border-amber-600/40 bg-amber-600/10 text-amber-700 dark:text-amber-400",
}

function jobStages(job: Job): JobStage[] {
  return job.progress.stages ?? []
}

export function JobTable({ jobs }: { jobs: Job[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (jobs.length === 0) {
    return <p className="text-sm text-muted-foreground">No jobs yet.</p>
  }
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table className="table-fixed">
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead className="w-8">
              <span className="sr-only">Details</span>
            </TableHead>
            <TableHead className="w-64">Kind</TableHead>
            <TableHead className="w-28">Status</TableHead>
            <TableHead>Progress</TableHead>
            <TableHead className="w-36">Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => {
            const stages = jobStages(job)
            const expanded = expandedId === job.id && stages.length > 0
            return (
              <Fragment key={job.id}>
                <TableRow
                  className={cn(stages.length > 0 && "cursor-pointer")}
                  onClick={() => {
                    if (stages.length > 0) setExpandedId(expanded ? null : job.id)
                  }}
                >
                  <TableCell className="pr-0">
                    {stages.length > 0 && (
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-controls={`job-stages-${job.id}`}
                        aria-label="Stage details"
                        onClick={(e) => {
                          // The row onClick is the pointer convenience; don't double-toggle.
                          e.stopPropagation()
                          setExpandedId(expanded ? null : job.id)
                        }}
                        className="rounded-sm p-1 align-middle focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
                      >
                        <CaretRightIcon
                          className={cn("size-3 transition-transform", expanded && "rotate-90")}
                        />
                      </button>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{job.kind}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={STATUS_BADGES[job.status]}>
                      {job.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="truncate text-sm text-muted-foreground">
                    {progressSummary(job, stages)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {relativeTime(job.created_at).label}
                  </TableCell>
                </TableRow>
                {expanded && (
                  <TableRow id={`job-stages-${job.id}`} className="hover:bg-transparent">
                    <TableCell colSpan={5} className="bg-muted/30 p-0">
                      <JobStages stages={stages} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function progressSummary(job: Job, stages: JobStage[]): string {
  if (stages.length === 0) return job.status === "failed" ? (job.error ?? "failed") : "—"
  const done = stages.filter((stage) => stageStatus(stage) === "completed").length
  const failed = stages.filter((stage) => stageStatus(stage) === "failed").length
  const running = stages.find((stage) => stageStatus(stage) === "running")
  const counts = `${done}/${stages.length}` + (failed > 0 ? ` · ${failed} failed` : "")
  return running ? `${counts} — ${running.label}` : counts
}
