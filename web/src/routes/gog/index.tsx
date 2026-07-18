import { getGetGogStatusSuspenseQueryOptions, useGetGogStatusSuspense } from "@/lib/api/client"
import { libraryListQueryOptions } from "@/lib/queries"
import { createFileRoute } from "@tanstack/react-router"
import { NotConnected } from "@/routes/gog/-components/not-connected"
import { GogLibrary } from "@/routes/gog/-components/gog-library"

export const Route = createFileRoute("/gog/")({
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(getGetGogStatusSuspenseQueryOptions()),
      queryClient.ensureInfiniteQueryData(libraryListQueryOptions()),
    ]),
  component: RouteComponent,
  staticData: {
    title: "GOG",
  },
})

function RouteComponent() {
  const { data: status } = useGetGogStatusSuspense()
  if (!status.connected) return <NotConnected />
  return <GogLibrary />
}
