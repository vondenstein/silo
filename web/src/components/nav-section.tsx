import type { ComponentPropsWithoutRef, ReactNode } from "react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { Link } from "@tanstack/react-router"

export function NavSection({
  items,
  label,
  ...props
}: {
  items: {
    name: string
    url: string
    icon: ReactNode
  }[]
  label?: string
} & ComponentPropsWithoutRef<typeof SidebarGroup>) {
  return (
    <SidebarGroup {...props}>
      {label && <SidebarGroupLabel>{label}</SidebarGroupLabel>}
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => (
            // Keyed by url — library names are not unique.
            <SidebarMenuItem key={item.url}>
              <SidebarMenuButton asChild>
                <Link to={item.url} activeProps={{ "data-active": "true" }}>
                  {item.icon}
                  <span>{item.name}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
