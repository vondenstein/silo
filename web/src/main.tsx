import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider, createRouter } from "@tanstack/react-router"
import "./index.css"
import { routeTree } from "./routeTree.gen"
import { queryClient } from "@/lib/query-client"
import { RouteError, RoutePending } from "@/components/route-fallbacks"

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0,
  defaultPendingComponent: RoutePending,
  defaultErrorComponent: RouteError,
})

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
  interface StaticDataRouteOption {
    title?: string
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
