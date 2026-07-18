import { LoadMoreButton } from "@/components/load-more-button"
import { jobListQueryOptions } from "@/lib/queries"
import { JobTable } from "@/routes/jobs/-components/job-table"
import { useSuspenseInfiniteQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"

export const Route = createFileRoute("/jobs/")({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureInfiniteQueryData(jobListQueryOptions()),
  component: RouteComponent,
  staticData: {
    title: "Jobs",
  },
})

function RouteComponent() {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useSuspenseInfiniteQuery({
    ...jobListQueryOptions(),
    // Poll only while work is active.
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) =>
        page.items.some((job) => job.status === "pending" || job.status === "running"),
      )
        ? 2000
        : false,
  })
  const jobs = data.pages.flatMap((page) => page.items)

  return (
    <div className="flex flex-col gap-4 px-4 lg:px-6">
      <JobTable jobs={jobs} />
      {hasNextPage && (
        <div className="flex justify-center">
          <LoadMoreButton isFetchingNextPage={isFetchingNextPage} onClick={() => fetchNextPage()} />
        </div>
      )}
    </div>
  )
}
