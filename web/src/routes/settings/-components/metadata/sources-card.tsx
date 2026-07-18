import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  getListMetadataSourcesQueryKey,
  useListMetadataSources,
  useUpdateMetadataSource,
} from "@/lib/api/client"
import type { MetadataSource } from "@/lib/api/model"
import { SettingsCard } from "@/routes/settings/-components/settings-card"

export function SourcesCard() {
  const { data: sources = [] } = useListMetadataSources()

  return (
    <SettingsCard
      title="Metadata sources"
      description="Fetch order and pacing. The lowest priority wins conflicts after a game's
        preferred source; the interval throttles API requests (blank = the source's default)."
    >
      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader className="bg-muted">
            <TableRow>
              <TableHead>Source</TableHead>
              <TableHead className="w-24">Enabled</TableHead>
              <TableHead className="w-28">Priority</TableHead>
              <TableHead className="w-36">Interval (ms)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sources.map((source) => (
              <SourceRow key={source.id} source={source} />
            ))}
          </TableBody>
        </Table>
      </div>
    </SettingsCard>
  )
}

function SourceRow({ source }: { source: MetadataSource }) {
  const mutation = useUpdateMetadataSource({
    mutation: {
      meta: {
        errorToast: "Failed to update source",
        invalidates: [getListMetadataSourcesQueryKey()],
      },
    },
  })

  return (
    <TableRow>
      <TableCell className="font-medium">{source.name}</TableCell>
      <TableCell>
        <Switch
          checked={source.enabled}
          onCheckedChange={(enabled) => mutation.mutate({ sourceId: source.id, data: { enabled } })}
          // The awaited invalidation delays the checked flip; hold the control meanwhile.
          disabled={mutation.isPending}
          aria-label={`Enable ${source.name}`}
        />
      </TableCell>
      {/* key-remount: a confirmed server change re-seeds these uncontrolled inputs'
          defaultValue; typing alone must not reset them mid-edit. */}
      <TableCell>
        <Input
          key={`priority-${source.priority}`}
          type="number"
          min={0}
          defaultValue={source.priority}
          className="w-20"
          aria-label={`${source.name} priority`}
          onBlur={(e) => {
            const value = Number(e.target.value)
            if (Number.isInteger(value) && value >= 0 && value !== source.priority) {
              mutation.mutate({ sourceId: source.id, data: { priority: value } })
            }
          }}
        />
      </TableCell>
      <TableCell>
        <Input
          key={`interval-${source.request_interval_ms ?? "default"}`}
          type="number"
          min={0}
          defaultValue={source.request_interval_ms ?? ""}
          placeholder="default"
          className="w-28"
          aria-label={`${source.name} request interval`}
          onBlur={(e) => {
            const raw = e.target.value.trim()
            const next = raw === "" ? null : Number(raw)
            if (next !== null && (!Number.isInteger(next) || next < 0)) return
            if (next !== (source.request_interval_ms ?? null)) {
              mutation.mutate({ sourceId: source.id, data: { request_interval_ms: next } })
            }
          }}
        />
      </TableCell>
    </TableRow>
  )
}
