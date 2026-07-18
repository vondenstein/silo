import { Button } from "@/components/ui/button"
import { useActiveJobs } from "@/hooks/use-active-jobs"
import {
  getGetGameQueryKey,
  getListGamesInfiniteQueryKey,
  useFetchGameMetadata,
} from "@/lib/api/client"
import { JobKind } from "@/lib/api/model"
import { JOB_LIST_KEYS } from "@/lib/queries"
import { queryClient } from "@/lib/query-client"
import { CloudArrowDownIcon, SpinnerGapIcon } from "@phosphor-icons/react"

export function FetchMetadataButton({ gameId }: { gameId: string }) {
  const activeFetches = useActiveJobs(JobKind.fetch_metadata, (finished) => {
    // When this game's fetch finishes, pull the freshly resolved scalars + covers.
    if (finished.some((job) => (job.payload.game_id as string) === gameId)) {
      queryClient.invalidateQueries({ queryKey: getGetGameQueryKey(gameId) })
      queryClient.invalidateQueries({ queryKey: getListGamesInfiniteQueryKey() })
    }
  })
  const fetching = activeFetches.some((job) => (job.payload.game_id as string) === gameId)

  const fetchMutation = useFetchGameMetadata({
    mutation: {
      meta: { errorToast: "Failed to start metadata fetch", invalidates: JOB_LIST_KEYS },
    },
  })

  if (fetching || fetchMutation.isPending) {
    return (
      <Button variant="outline" disabled>
        <SpinnerGapIcon className="animate-spin" />
        Fetching…
      </Button>
    )
  }
  return (
    <Button variant="outline" onClick={() => fetchMutation.mutate({ gameId })}>
      <CloudArrowDownIcon />
      Fetch metadata
    </Button>
  )
}
