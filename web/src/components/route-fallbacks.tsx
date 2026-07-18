import { useQueryErrorResetBoundary } from "@tanstack/react-query"
import { useRouter, type ErrorComponentProps } from "@tanstack/react-router"
import { useEffect } from "react"

import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/fetch-mutator"

export function RoutePending() {
  return <p className="px-4 py-16 text-center text-sm text-muted-foreground">Loading…</p>
}

export function RouteError({ error }: ErrorComponentProps) {
  const router = useRouter()
  const queryErrorResetBoundary = useQueryErrorResetBoundary()

  useEffect(() => {
    queryErrorResetBoundary.reset()
  }, [queryErrorResetBoundary])

  return (
    <div className="flex flex-col items-center gap-3 px-4 py-16">
      <p className="text-sm text-destructive">
        {error instanceof ApiError ? error.message : "Something went wrong"}
      </p>
      <Button variant="outline" size="sm" onClick={() => router.invalidate()}>
        Try again
      </Button>
    </div>
  )
}
