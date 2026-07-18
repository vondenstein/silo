import { LoadMoreButton } from "@/components/load-more-button"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { libraryListQueryOptions } from "@/lib/queries"
import { LibraryRow, NewLibraryRow } from "@/routes/settings/-components/libraries/library-rows"
import { SettingsCard } from "@/routes/settings/-components/settings-card"
import { PlusIcon } from "@phosphor-icons/react"
import { useSuspenseInfiniteQuery } from "@tanstack/react-query"
import { useState } from "react"

export function LibrariesSection() {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useSuspenseInfiniteQuery(libraryListQueryOptions())
  const libraries = data.pages.flatMap((page) => page.items)
  const [creating, setCreating] = useState(false)

  return (
    <SettingsCard
      title="Libraries"
      description="Group your games into separate collections. Each game belongs to exactly one library."
      action={
        <Button size="sm" onClick={() => setCreating(true)} disabled={creating}>
          <PlusIcon weight="bold" /> New Library
        </Button>
      }
    >
      <div className="overflow-hidden rounded-lg border">
        <Table className="table-fixed">
          <TableHeader className="bg-muted">
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead className="w-1/3">Slug</TableHead>
              <TableHead className="w-24 text-right">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {creating && (
              <NewLibraryRow
                existingSlugs={new Set(libraries.map((l) => l.slug))}
                onClose={() => setCreating(false)}
              />
            )}
            {libraries.map((library) => (
              <LibraryRow key={library.id} library={library} />
            ))}
          </TableBody>
        </Table>
      </div>
      {hasNextPage && (
        <LoadMoreButton
          size="sm"
          className="mt-3"
          isFetchingNextPage={isFetchingNextPage}
          onClick={() => fetchNextPage()}
        />
      )}
    </SettingsCard>
  )
}
