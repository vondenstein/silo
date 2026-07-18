import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
} from "@/components/ui/sidebar"
import {
  getGetGameAssetsQueryKey,
  getGetGameQueryKey,
  getListGamesInfiniteQueryKey,
  useLockField,
  useSetGameAssets,
  useUnlockField,
  useUpdateGame,
} from "@/lib/api/client"
import { AssetKind } from "@/lib/api/model"
import type { GameDetail, GamePatch } from "@/lib/api/model"
import { queryClient } from "@/lib/query-client"
import { DetailsSection } from "@/routes/games/-components/details-section"
import { EditSessionProvider, useEditSessionState } from "@/routes/games/-components/edit-session"
import type { SectionKey } from "@/routes/games/-components/edit-session"
import { CoverSection } from "@/routes/games/-components/cover-section"
import { GroupsSection } from "@/routes/games/-components/groups-section"
import { IdentitySection } from "@/routes/games/-components/identity-section"
import { ScreenshotsSection } from "@/routes/games/-components/screenshots-section"
import { SerialsSection } from "@/routes/games/-components/serials-section"
import {
  FingerprintIcon,
  HashIcon,
  ImageIcon,
  ImagesIcon,
  InfoIcon,
  TagIcon,
} from "@phosphor-icons/react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

// The edit dialog is the game-management hub: one transactional editing
// session — sections stage changes, the shell's Save commits them together.
// The sidebar-in-dialog shell is intentional (schema-sketch §10).
const SECTIONS = [
  { key: "details", label: "Details", icon: InfoIcon },
  { key: "identity", label: "Identity", icon: FingerprintIcon },
  { key: "cover", label: "Cover", icon: ImageIcon },
  { key: "screenshots", label: "Screenshots", icon: ImagesIcon },
  { key: "groups", label: "Groups", icon: TagIcon },
  { key: "serials", label: "Serial numbers", icon: HashIcon },
] as const

export function EditGameDialog({ game }: { game: GameDetail }) {
  const [open, setOpen] = useState(false)
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)
  const dirtyRef = useRef(false)
  const close = () => {
    dirtyRef.current = false
    setConfirmingDiscard(false)
    setOpen(false)
  }
  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (next) setOpen(true)
          else if (dirtyRef.current) setConfirmingDiscard(true)
          else close()
        }}
      >
        <DialogTrigger asChild>
          <Button variant="outline">Edit</Button>
        </DialogTrigger>
        <DialogContent className="flex h-[85dvh] flex-col gap-0 overflow-hidden p-0 md:h-[620px] md:max-w-[700px] lg:max-w-[800px]">
          <DialogTitle className="sr-only">Edit game</DialogTitle>
          <DialogDescription className="sr-only">Manage this game's metadata.</DialogDescription>
          <DialogBody
            game={game}
            onSaved={close}
            onDirtyChange={(dirty) => {
              dirtyRef.current = dirty
            }}
          />
        </DialogContent>
      </Dialog>
      <AlertDialog open={confirmingDiscard} onOpenChange={setConfirmingDiscard}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Your edits in this dialog haven't been saved.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction onClick={close}>Discard</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function DialogBody({
  game,
  onSaved,
  onDirtyChange,
}: {
  game: GameDetail
  onSaved: () => void
  onDirtyChange: (dirty: boolean) => void
}) {
  const [section, setSection] = useState<SectionKey>("details")
  const [visited, setVisited] = useState(() => new Set<SectionKey>(["details"]))
  const [generations, setGenerations] = useState<Partial<Record<SectionKey, number>>>({})
  const [saving, setSaving] = useState(false)
  const { session, anyDirty, anyInvalid, lockOps, collectAll } = useEditSessionState(game)

  const activate = (key: SectionKey) => {
    setSection(key)
    setVisited((prev) => {
      if (prev.has(key)) return prev
      const next = new Set(prev)
      next.add(key)
      return next
    })
  }

  useEffect(() => {
    onDirtyChange(anyDirty || saving)
  }, [onDirtyChange, anyDirty, saving])

  const updateGame = useUpdateGame({
    mutation: { meta: { errorToast: "Failed to save changes" } },
  })
  const putCover = useSetGameAssets({
    mutation: { meta: { errorToast: "Failed to update cover" } },
  })
  const putScreenshots = useSetGameAssets({
    mutation: { meta: { errorToast: "Failed to update screenshots" } },
  })
  const lockField = useLockField({ mutation: { meta: { errorToast: "Failed to update locks" } } })
  const unlockField = useUnlockField({
    mutation: { meta: { errorToast: "Failed to update locks" } },
  })

  const save = async () => {
    setSaving(true)
    const succeeded: SectionKey[] = []
    let failed = false
    try {
      const contributions = collectAll()
      const patchEntries = [...contributions].filter(([, c]) => c.patch)
      if (patchEntries.length > 0) {
        // Details, groups, and serials write disjoint GamePatch keys.
        const patch: GamePatch = Object.assign({}, ...patchEntries.map(([, c]) => c.patch))
        await updateGame.mutateAsync({ gameId: game.id, data: patch })
        succeeded.push(...patchEntries.map(([key]) => key))
      }
      for (const [key, contribution] of contributions) {
        if (!contribution.assetPut) continue
        const put = contribution.assetPut.kind === AssetKind.cover ? putCover : putScreenshots
        await put.mutateAsync({
          gameId: game.id,
          kind: contribution.assetPut.kind,
          data: { blobs: contribution.assetPut.blobs },
        })
        succeeded.push(key)
      }
      await Promise.all([
        ...lockOps.toLock.map((fieldKey) => lockField.mutateAsync({ gameId: game.id, fieldKey })),
        ...lockOps.toUnlock.map((fieldKey) =>
          unlockField.mutateAsync({ gameId: game.id, fieldKey }),
        ),
      ])
    } catch {
      // The global MutationCache onError already toasted the failed step.
      failed = true
    } finally {
      // The server may have changed on any partial success — refetch either way,
      // before the generation bumps so remounted sections re-init from fresh data.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: getGetGameQueryKey(game.id) }),
        queryClient.invalidateQueries({ queryKey: getGetGameAssetsQueryKey(game.id) }),
      ])
      queryClient.invalidateQueries({ queryKey: getListGamesInfiniteQueryKey() })
      setSaving(false)
    }
    if (!failed) {
      toast.success("Game updated")
      onSaved()
    } else if (succeeded.length > 0) {
      // Partial success: remount the committed sections so they re-baseline clean;
      // the failed section keeps its draft.
      setGenerations((prev) => {
        const next = { ...prev }
        for (const key of succeeded) next[key] = (next[key] ?? 0) + 1
        return next
      })
    }
  }

  const sectionClass = (key: SectionKey, fill = true) =>
    section === key ? (fill ? "flex flex-1 flex-col" : undefined) : "hidden"

  return (
    <>
      <div className="border-b p-3 pr-12 md:hidden">
        <Select value={section} onValueChange={(value) => activate(value as SectionKey)}>
          <SelectTrigger className="w-full" aria-label="Dialog section">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SECTIONS.map((s) => (
              <SelectItem key={s.key} value={s.key}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {/* min-h-0 overrides the provider's min-h-svh — the cause of the sidebar
          running past the dialog's bottom edge. */}
      <SidebarProvider className="min-h-0 flex-1">
        {/* The floating variant's glass panel, on a static sidebar — the real
            variant="floating" is viewport-fixed (h-svh) and overflows dialogs. */}
        <Sidebar
          collapsible="none"
          className="m-2 hidden h-auto rounded-2xl shadow-sm ring-1 ring-sidebar-border md:flex"
        >
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {SECTIONS.map((s) => (
                    <SidebarMenuItem key={s.key}>
                      <SidebarMenuButton
                        isActive={s.key === section}
                        onClick={() => activate(s.key)}
                      >
                        <s.icon /> {s.label}
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
        </Sidebar>
        <main className="flex flex-1 flex-col overflow-y-auto p-6">
          <EditSessionProvider value={session}>
            {/* Visited sections stay mounted (hidden) so unsaved edits survive
                switching — the global Save collects from every one of them. */}
            {visited.has("details") && (
              <div
                key={`details-${generations.details ?? 0}`}
                className={sectionClass("details", false)}
              >
                <DetailsSection game={game} />
              </div>
            )}
            {visited.has("identity") && (
              <div
                key={`identity-${generations.identity ?? 0}`}
                className={sectionClass("identity")}
              >
                <IdentitySection game={game} />
              </div>
            )}
            {visited.has("cover") && (
              <div key={`cover-${generations.cover ?? 0}`} className={sectionClass("cover")}>
                <CoverSection game={game} />
              </div>
            )}
            {visited.has("screenshots") && (
              <div
                key={`screenshots-${generations.screenshots ?? 0}`}
                className={sectionClass("screenshots")}
              >
                <ScreenshotsSection game={game} />
              </div>
            )}
            {visited.has("groups") && (
              <div key={`groups-${generations.groups ?? 0}`} className={sectionClass("groups")}>
                <GroupsSection game={game} />
              </div>
            )}
            {visited.has("serials") && (
              <div key={`serials-${generations.serials ?? 0}`} className={sectionClass("serials")}>
                <SerialsSection game={game} />
              </div>
            )}
          </EditSessionProvider>
        </main>
      </SidebarProvider>
      <DialogFooter className="border-t px-6 py-4">
        <Button onClick={save} disabled={!anyDirty || anyInvalid || saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </DialogFooter>
    </>
  )
}
