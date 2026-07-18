import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { useRouterState } from "@tanstack/react-router"

export function SiteHeader() {
  const matches = useRouterState({ select: (s) => s.matches })
  const title = matches[matches.length - 1]?.staticData?.title ?? "Silo"

  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 border-b">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator
          orientation="vertical"
          className="mx-2 data-[orientation=vertical]:h-4 data-vertical:self-center"
        />
        <h1 className="text-base font-medium">{title}</h1>
      </div>
    </header>
  )
}
