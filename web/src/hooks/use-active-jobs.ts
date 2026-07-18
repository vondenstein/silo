import { useListJobs } from "@/lib/api/client"
import type { Job, JobKind } from "@/lib/api/model"
import { useEffect, useRef } from "react"

const NONE: Job[] = []

/**
 * Poll the active (pending/running) jobs of a kind — one data-driven interval
 * per §9 — and report the jobs that leave the active set to `onFinish`.
 */
export function useActiveJobs(kind: JobKind, onFinish?: (finished: Job[]) => void): Job[] {
  const { data } = useListJobs(
    { kind, status: ["pending", "running"] },
    { query: { refetchInterval: (query) => (query.state.data?.items.length ? 2000 : false) } },
  )
  const active = data?.items ?? NONE

  const onFinishRef = useRef(onFinish)
  useEffect(() => {
    onFinishRef.current = onFinish
  })

  const previous = useRef(active)
  useEffect(() => {
    const activeIds = new Set(active.map((job) => job.id))
    const finished = previous.current.filter((job) => !activeIds.has(job.id))
    previous.current = active
    if (finished.length > 0) onFinishRef.current?.(finished)
  }, [active])

  return active
}
