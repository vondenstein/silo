import { Outlet, createRootRouteWithContext } from "@tanstack/react-router"
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools"
import type { CSSProperties } from "react"
import type { QueryClient } from "@tanstack/react-query"
import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import { AppSidebar } from "@/components/app-sidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { SiteHeader } from "@/components/site-header"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ThemeProvider } from "@/components/theme-provider"
import { Toaster } from "@/components/ui/sonner"

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootComponent,
})

function RootComponent() {
  // The SPA half of the vendored sidebar's cookie persistence: it writes
  // sidebar_state on toggle; shadcn's SSR setups read it back server-side.
  const sidebarState = document.cookie.match(/(?:^|; )sidebar_state=(true|false)/)?.[1]
  return (
    <>
      <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
        <TooltipProvider>
          <SidebarProvider
            defaultOpen={sidebarState !== "false"}
            style={
              {
                "--sidebar-width": "calc(var(--spacing) * 72)",
                "--header-height": "calc(var(--spacing) * 12)",
              } as CSSProperties
            }
          >
            <AppSidebar variant="inset" />
            <SidebarInset>
              <SiteHeader />
              <div className="flex flex-1 flex-col">
                <div className="@container/main flex flex-1 flex-col">
                  <div className="flex flex-1 flex-col gap-4 py-4 md:gap-6 md:py-6">
                    <Outlet />
                    <Toaster />
                  </div>
                </div>
              </div>
            </SidebarInset>
          </SidebarProvider>
        </TooltipProvider>
      </ThemeProvider>
      <TanStackRouterDevtools />
      <ReactQueryDevtools />
    </>
  )
}
