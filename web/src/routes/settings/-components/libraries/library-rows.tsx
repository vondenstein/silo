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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { TableCell, TableRow } from "@/components/ui/table"
import {
  getListLibrariesInfiniteQueryKey,
  getListLibrariesQueryKey,
  useCreateLibrary,
  useDeleteLibrary,
  useUpdateLibrary,
} from "@/lib/api/client"
import type { Library } from "@/lib/api/model"
import { isValidSlug, slugify } from "@/lib/slug"
import { CheckIcon, DotsThreeIcon, XIcon } from "@phosphor-icons/react"
import { useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"

// The settings table's infinite list + the sidebar's plain list.
const LIBRARY_KEYS = [getListLibrariesInfiniteQueryKey(), getListLibrariesQueryKey()]

export function NewLibraryRow({
  existingSlugs,
  onClose,
}: {
  existingSlugs: Set<string>
  onClose: () => void
}) {
  const [name, setName] = useState("")
  const [slug, setSlug] = useState("")
  const [slugTouched, setSlugTouched] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    nameRef.current?.focus()
  }, [])

  const effectiveSlug = slugTouched ? slug : slugify(name)
  const slugTaken = effectiveSlug.length > 0 && existingSlugs.has(effectiveSlug)
  const slugInvalid = effectiveSlug.length > 0 && !isValidSlug(effectiveSlug)
  const canSubmit = name.trim().length > 0 && effectiveSlug.length > 0 && !slugTaken && !slugInvalid

  const createMutation = useCreateLibrary({
    mutation: {
      meta: {
        successToast: "Library created",
        errorToast: "Failed to create library",
        invalidates: LIBRARY_KEYS,
      },
      onSuccess: onClose,
    },
  })

  const submit = () => {
    // isPending guards the keyboard path — Enter can fire faster than the disabled button.
    if (!canSubmit || createMutation.isPending) return
    createMutation.mutate({ data: { slug: effectiveSlug, name: name.trim() } })
  }

  return (
    <TableRow className="bg-muted/30">
      <TableCell>
        <Input
          ref={nameRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit()
            if (e.key === "Escape") onClose()
          }}
          placeholder="Library name"
          aria-label="Library name"
        />
      </TableCell>
      <TableCell>
        <Input
          value={effectiveSlug}
          onChange={(e) => {
            setSlugTouched(true)
            setSlug(e.target.value)
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit()
            if (e.key === "Escape") onClose()
          }}
          placeholder="library-slug"
          aria-label="Library slug"
          aria-invalid={slugTaken || slugInvalid}
          aria-describedby={slugTaken || slugInvalid ? "new-library-slug-error" : undefined}
          className="font-mono"
        />
        {(slugTaken || slugInvalid) && (
          <p id="new-library-slug-error" className="mt-1 text-xs text-destructive">
            {slugTaken ? "Slug already in use" : "Lowercase, hyphen-separated"}
          </p>
        )}
      </TableCell>
      <TableCell className="text-right">
        <RowActions>
          <Button
            variant="ghost"
            size="icon"
            onClick={submit}
            disabled={!canSubmit || createMutation.isPending}
            aria-label="Save"
          >
            <CheckIcon weight="bold" />
          </Button>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Cancel">
            <XIcon weight="bold" />
          </Button>
        </RowActions>
      </TableCell>
    </TableRow>
  )
}

export function LibraryRow({ library }: { library: Library }) {
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState(library.name)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  const updateMutation = useUpdateLibrary({
    mutation: {
      meta: { errorToast: "Failed to rename library", invalidates: LIBRARY_KEYS },
      onSuccess: () => setEditing(false),
    },
  })

  const startEditing = () => {
    setDraftName(library.name)
    setEditing(true)
  }

  const save = () => {
    // Enter triggers save and then blurs — don't let the blur PATCH again.
    if (updateMutation.isPending) return
    const next = draftName.trim()
    if (!next) return
    if (next === library.name) {
      setEditing(false)
      return
    }
    updateMutation.mutate({ libraryId: library.id, data: { name: next } })
  }

  return (
    <TableRow>
      <TableCell className="font-medium">
        {editing ? (
          <Input
            ref={inputRef}
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === "Enter") save()
              if (e.key === "Escape") setEditing(false)
            }}
            aria-label="Library name"
          />
        ) : (
          library.name
        )}
      </TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">{library.slug}</TableCell>
      <TableCell className="text-right">
        <RowActions>
          {!editing && (
            <>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label="Row actions">
                    <DotsThreeIcon weight="bold" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={startEditing}>Rename</DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => setDeleteOpen(true)}>
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <DeleteLibraryDialog
                library={library}
                open={deleteOpen}
                onOpenChange={setDeleteOpen}
              />
            </>
          )}
        </RowActions>
      </TableCell>
    </TableRow>
  )
}

function RowActions({ children }: { children: ReactNode }) {
  return <div className="flex h-9 items-center justify-end gap-1">{children}</div>
}

function DeleteLibraryDialog({
  library,
  open,
  onOpenChange,
}: {
  library: Library
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const deleteMutation = useDeleteLibrary({
    mutation: {
      meta: {
        successToast: `Deleted "${library.name}"`,
        errorToast: "Failed to delete library",
        invalidates: LIBRARY_KEYS,
      },
    },
  })

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete library?</AlertDialogTitle>
          <AlertDialogDescription>
            {`"${library.name}" will be deleted. A library that still contains games can't be deleted.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={() => deleteMutation.mutate({ libraryId: library.id })}>
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
