import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import {
  getListIdentificationDatasetsQueryKey,
  useDiscoverIdentificationDatasets,
  useRefreshIdentificationDataset,
  useUpdateIdentificationDataset,
} from "@/lib/api/client"
import type { Dataset } from "@/lib/api/model"
import { JOB_LIST_KEYS } from "@/lib/queries"
import { ArrowsClockwiseIcon, MagnifyingGlassIcon } from "@phosphor-icons/react"
import { useState } from "react"
import { toast } from "sonner"

export function ManageDialog({
  open,
  onOpenChange,
  datasets,
  isPending,
  isError,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  datasets: Dataset[]
  isPending: boolean
  isError: boolean
}) {
  const [query, setQuery] = useState("")
  const filtered = query.trim()
    ? datasets.filter((dataset) => dataset.name.toLowerCase().includes(query.toLowerCase()))
    : datasets
  const discover = useDiscoverIdentificationDatasets({
    mutation: {
      meta: {
        errorToast: "Failed to fetch Redump's system list",
        invalidates: [getListIdentificationDatasetsQueryKey()],
      },
      onSuccess: (result) => toast.success(`${result.dataset_count} datasets available`),
    },
  })
  const update = useUpdateIdentificationDataset({
    mutation: {
      meta: {
        errorToast: "Failed to update the dataset",
        invalidates: [getListIdentificationDatasetsQueryKey()],
      },
    },
  })
  const refresh = useRefreshIdentificationDataset({
    mutation: {
      meta: {
        errorToast: "Failed to queue the refresh",
        invalidates: JOB_LIST_KEYS,
      },
    },
  })

  // Old-app behavior: newly enabled datasets start their DAT refresh right away
  // (scoped to empty datasets — re-enabling a populated one shouldn't re-download).
  const toggle = (dataset: Dataset, enabled: boolean) => {
    update.mutate(
      { datasetId: dataset.id, data: { enabled } },
      {
        onSuccess: () => {
          if (enabled && dataset.signature_count === 0) {
            refresh.mutate(
              { datasetId: dataset.id },
              {
                onSuccess: () => toast.success(`Refreshing "${dataset.name}" — follow it in Jobs`),
              },
            )
          }
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-[640px]">
        <DialogTitle>Redump datasets</DialogTitle>
        <DialogDescription>
          Enable the datasets you archive, then refresh to import their signatures.
        </DialogDescription>
        {isPending ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Loading…</p>
        ) : isError ? (
          <p className="py-8 text-center text-sm text-destructive">Couldn't load the datasets.</p>
        ) : datasets.length === 0 ? (
          <div className="space-y-3 py-8 text-center">
            <p className="text-sm text-muted-foreground">
              No datasets yet — discover the available datasets to get started.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => discover.mutate({ slug: "redump" })}
              disabled={discover.isPending}
            >
              <ArrowsClockwiseIcon />
              {discover.isPending ? "Discovering…" : "Discover datasets"}
            </Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <MagnifyingGlassIcon className="absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search datasets…"
                  className="pl-9"
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => discover.mutate({ slug: "redump" })}
                disabled={discover.isPending}
              >
                <ArrowsClockwiseIcon />
                {discover.isPending ? "Discovering…" : "Discover datasets"}
              </Button>
            </div>
            <div className="h-80 overflow-y-auto rounded-lg border">
              {filtered.length === 0 ? (
                <p className="flex h-full items-center justify-center px-6 text-center text-sm text-muted-foreground">
                  No datasets match "{query}".
                </p>
              ) : (
                <Table>
                  <TableBody>
                    {filtered.map((dataset) => (
                      <TableRow key={dataset.id}>
                        <TableCell>{dataset.name}</TableCell>
                        <TableCell className="w-28 text-right text-xs text-muted-foreground tabular-nums">
                          {dataset.signature_count > 0
                            ? dataset.signature_count.toLocaleString()
                            : "—"}
                        </TableCell>
                        <TableCell className="w-16 text-right">
                          <Switch
                            checked={dataset.enabled}
                            onCheckedChange={(enabled) => toggle(dataset, enabled)}
                            aria-label={`Enable ${dataset.name}`}
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
