import { createFileRoute } from "@tanstack/react-router"
import type { ComponentType } from "react"
import { z } from "zod"

import { libraryListQueryOptions } from "@/lib/queries"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { GogSection } from "@/routes/settings/-components/gog/gog-section"
import { LibrariesSection } from "@/routes/settings/-components/libraries/libraries-section"
import { RedumpSection } from "@/routes/settings/-components/redump/redump-section"
import { MetadataSection } from "@/routes/settings/-components/metadata/metadata-section"

const TAB_VALUES = ["libraries", "gog", "redump", "metadata"] as const

const TABS: Record<(typeof TAB_VALUES)[number], { label: string; Section: ComponentType }> = {
  libraries: { label: "Libraries", Section: LibrariesSection },
  gog: { label: "GOG", Section: GogSection },
  redump: { label: "Redump", Section: RedumpSection },
  metadata: { label: "Metadata", Section: MetadataSection },
}

const searchSchema = z.object({
  // catch, not default: a stale/typo'd ?tab= falls back instead of erroring the route.
  tab: z.enum(TAB_VALUES).catch("libraries"),
})

export const Route = createFileRoute("/settings/")({
  validateSearch: searchSchema,
  // §9 boundary: the loader owns the primary tab's data (libraries); the other
  // tabs are secondary panes that client-fetch with their own loading/error triads.
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureInfiniteQueryData(libraryListQueryOptions()),
  staticData: {
    title: "Settings",
  },
  component: RouteComponent,
})

function RouteComponent() {
  const { tab } = Route.useSearch()
  const navigate = Route.useNavigate()

  return (
    <Tabs
      className="w-full gap-6"
      value={tab}
      onValueChange={(value) => navigate({ search: { tab: value as typeof tab } })}
    >
      <div className="flex items-center justify-between px-4 lg:px-6">
        <TabsList>
          {TAB_VALUES.map((value) => (
            <TabsTrigger key={value} value={value}>
              {TABS[value].label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>

      {TAB_VALUES.map((value) => {
        const Section = TABS[value].Section
        return (
          <TabsContent key={value} value={value} className="flex flex-col gap-4 px-4 lg:px-6">
            <Section />
          </TabsContent>
        )
      })}
    </Tabs>
  )
}
