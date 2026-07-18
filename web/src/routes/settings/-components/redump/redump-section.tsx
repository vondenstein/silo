import { Button } from "@/components/ui/button"
import { useActiveJobs } from "@/hooks/use-active-jobs"
import {
  getListIdentificationDatasetsQueryKey,
  useListIdentificationDatasets,
  useRefreshIdentificationDatasets,
} from "@/lib/api/client"
import { JobKind } from "@/lib/api/model"
import { JOB_LIST_KEYS } from "@/lib/queries"
import { queryClient } from "@/lib/query-client"
import { relativeTime } from "@/lib/relative-time"
import { ManageDialog } from "@/routes/settings/-components/redump/manage-dialog"
import { SettingsCard } from "@/routes/settings/-components/settings-card"
import { ArrowsClockwiseIcon, GearIcon } from "@phosphor-icons/react"
import { useState } from "react"

export function RedumpSection() {
  const { data: datasets = [], isPending, isError } = useListIdentificationDatasets()
  const [manageOpen, setManageOpen] = useState(false)
  // Signature counts / refreshed_at update when queued refreshes land
  // (the single-dataset and sweep kinds are separate jobs).
  const invalidateDatasets = () =>
    queryClient.invalidateQueries({ queryKey: getListIdentificationDatasetsQueryKey() })
  useActiveJobs(JobKind.refresh_identification_dataset, invalidateDatasets)
  useActiveJobs(JobKind.refresh_identification_datasets, invalidateDatasets)
  const enabled = datasets.filter((dataset) => dataset.enabled)
  const signatures = enabled.reduce((sum, dataset) => sum + dataset.signature_count, 0)
  const stale = enabled.filter((dataset) => relativeTime(dataset.refreshed_at).stale).length
  const refreshedTimes = enabled.map((dataset) => dataset.refreshed_at).filter((t) => t != null)
  const updated = refreshedTimes.length
    ? relativeTime(refreshedTimes.reduce((a, b) => (a > b ? a : b))).label
    : null
  const refreshAll = useRefreshIdentificationDatasets({
    mutation: {
      meta: {
        successToast: "Refreshing datasets — follow it in Jobs",
        errorToast: "Failed to queue the refresh",
        invalidates: JOB_LIST_KEYS,
      },
    },
  })

  return (
    <SettingsCard
      title="Redump"
      description="Identify uploaded disc images against Redump's verified hash datasets."
      action={
        <div className="flex gap-2">
          {enabled.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => refreshAll.mutate()}
              disabled={refreshAll.isPending}
            >
              <ArrowsClockwiseIcon /> Refresh datasets
            </Button>
          )}
          <Button size="sm" onClick={() => setManageOpen(true)}>
            <GearIcon weight="bold" /> Manage datasets
          </Button>
        </div>
      }
    >
      {/* Loading/error before empty — a failed fetch must not read as "nothing configured". */}
      {isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : isError ? (
        <p className="text-sm text-destructive">Couldn't load the datasets.</p>
      ) : enabled.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-8 text-sm text-muted-foreground">
          <p>No datasets enabled yet.</p>
          <Button variant="outline" size="sm" onClick={() => setManageOpen(true)}>
            Browse available datasets
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {enabled.length} of {datasets.length} datasets enabled · {signatures.toLocaleString()}{" "}
          signatures
          {updated && <> · updated {updated}</>}
          {stale > 0 && (
            <span className="text-amber-600 dark:text-amber-400"> · {stale} stale</span>
          )}
        </p>
      )}
      <ManageDialog
        open={manageOpen}
        onOpenChange={setManageOpen}
        datasets={datasets}
        isPending={isPending}
        isError={isError}
      />
    </SettingsCard>
  )
}
