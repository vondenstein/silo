import type { ComponentProps } from "react"

import { NavSection } from "@/components/nav-section"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import {
  AirTrafficControlIcon,
  GameControllerIcon,
  GearIcon,
  QuestionIcon,
  DatabaseIcon,
  BoxArrowUpIcon,
  BarnIcon,
  FolderIcon,
} from "@phosphor-icons/react"
import { Link } from "@tanstack/react-router"
import { useListLibraries } from "@/lib/api/client"

const navItems = {
  main: [
    {
      name: "All Games",
      url: "/games",
      icon: <GameControllerIcon />,
    },
  ],
  sources: [
    {
      name: "GOG",
      url: "/gog",
      icon: <DatabaseIcon />,
    },
    {
      name: "Upload",
      url: "/upload",
      icon: <BoxArrowUpIcon />,
    },
  ],
  admin: [
    {
      name: "Jobs",
      url: "/jobs",
      icon: <AirTrafficControlIcon />,
    },
    {
      name: "Settings",
      url: "/settings",
      icon: <GearIcon />,
    },
    {
      name: "Get Help",
      url: "#",
      icon: <QuestionIcon />,
    },
  ],
}

export function AppSidebar({ ...props }: ComponentProps<typeof Sidebar>) {
  const { data } = useListLibraries()
  const libraries = (data?.items ?? []).map((item) => ({
    name: item.name,
    url: `/libraries/${item.id}`,
    icon: <FolderIcon />,
  }))

  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild className="p-1.5!">
              <Link to="/">
                <BarnIcon className="size-5!" />
                <span className="text-base font-semibold">Silo</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavSection items={navItems.main} />
        {/* With one library, its page is content-identical to /games — the section
            would only duplicate the All Games link. Flip to > 0 if library pages
            ever grow their own surface. */}
        {libraries.length > 1 && <NavSection items={libraries} label="Libraries" />}
        <NavSection items={navItems.sources} label="Sources" />
        <NavSection items={navItems.admin} className="mt-auto" />
      </SidebarContent>
      <SidebarFooter />
    </Sidebar>
  )
}
