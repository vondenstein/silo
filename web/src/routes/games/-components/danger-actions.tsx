import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { getListGamesInfiniteQueryKey, useDeleteGame } from "@/lib/api/client"
import { SpinnerGapIcon } from "@phosphor-icons/react"
import { useNavigate } from "@tanstack/react-router"
import { toast } from "sonner"

export function DangerActions({
  gameId,
  libraryId,
  title,
}: {
  gameId: string
  libraryId: string
  title: string
}) {
  const navigate = useNavigate()

  const deleteMutation = useDeleteGame({
    mutation: {
      meta: {
        errorToast: "Failed to remove game",
        invalidates: [getListGamesInfiniteQueryKey()],
      },
      onSuccess: () => {
        toast.success(`Removed "${title}"`)
        navigate({ to: "/libraries/$libraryId", params: { libraryId } })
      },
    },
  })

  return (
    <div className="flex flex-wrap items-center gap-2 pt-2">
      <AlertDialog>
        <AlertDialogTrigger asChild>
          {/* The on-disk delete can be slow; hold the trigger until it lands. */}
          <Button variant="destructive" size="sm" disabled={deleteMutation.isPending}>
            {deleteMutation.isPending && <SpinnerGapIcon className="animate-spin" />}
            {deleteMutation.isPending ? "Removing…" : "Remove from library"}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove from library?</AlertDialogTitle>
            <AlertDialogDescription>
              {`"${title}" will be removed from your library and its files deleted from disk.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteMutation.mutate({ gameId, params: { delete_files: true } })}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
