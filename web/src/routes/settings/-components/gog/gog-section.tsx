import { ExternalLink } from "@/components/external-link"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { useAppForm } from "@/hooks/form"
import {
  getGetGogStatusQueryKey,
  useGetGogAuthUrl,
  useConnectGog,
  useDisconnectGog,
  useGetGogStatus,
} from "@/lib/api/client"
import { ConnectionBadge } from "@/routes/settings/-components/connection-badge"
import { DisconnectDialogButton } from "@/routes/settings/-components/disconnect-dialog-button"
import { SettingsCard } from "@/routes/settings/-components/settings-card"
import * as z from "zod"

/** Extract the auth code from a plain code, query fragment, or full redirect URL. */
function extractCode(input: string): string {
  const trimmed = input.trim()
  const match = trimmed.match(/(?:^|[?&])code=([^&]+)/)
  return match ? decodeURIComponent(match[1]) : trimmed
}

export function GogSection() {
  const { data: status, isLoading, isError, refetch } = useGetGogStatus()

  return (
    <SettingsCard
      title="GOG"
      description={
        <>
          Import games from a connected <ExternalLink href="https://gog.com">GOG.com</ExternalLink>{" "}
          account.
        </>
      }
      action={
        <ConnectionBadge isLoading={isLoading} isError={isError} connected={status?.connected} />
      }
    >
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <div className="flex items-center gap-3">
          <p className="text-sm text-muted-foreground">Couldn't load the GOG status.</p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}
      {!isLoading && !isError && !status?.connected && <DisconnectedView />}
      {!isLoading && !isError && status?.connected && <ConnectedView />}
    </SettingsCard>
  )
}

function ConnectForm() {
  const connectMutation = useConnectGog({
    mutation: {
      meta: {
        successToast: "Connected to GOG",
        errorToast: "GOG rejected the authorization code",
        invalidates: [getGetGogStatusQueryKey()],
      },
    },
  })

  const form = useAppForm({
    defaultValues: { code: "" },
    validators: {
      onSubmit: z.object({ code: z.string().trim().min(1, "Required") }),
    },
    onSubmit: async ({ value }) => {
      try {
        // Awaited so the submit button stays disabled through the exchange —
        // the OAuth code is single-use, so a double-click would burn it.
        await connectMutation.mutateAsync({ data: { code: extractCode(value.code) } })
      } catch {
        // The global MutationCache onError already toasted.
      }
    },
  })

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        form.handleSubmit()
      }}
      className="space-y-4"
    >
      <form.AppField name="code">
        {(f) => <f.TextField label="Auth Code" placeholder="Paste the auth code or the full URL" />}
      </form.AppField>
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline">
            Cancel
          </Button>
        </DialogClose>
        <Button type="submit" disabled={connectMutation.isPending}>
          {connectMutation.isPending ? "Connecting…" : "Connect"}
        </Button>
      </DialogFooter>
    </form>
  )
}

function DisconnectedView() {
  const { data: authUrlData, isError, refetch } = useGetGogAuthUrl()
  const authUrl = authUrlData?.url

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button>Connect</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect GOG account</DialogTitle>
          <DialogDescription>Authorize Silo to connect to your GOG library.</DialogDescription>
        </DialogHeader>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Log in</li>
          <li>
            {authUrl ? (
              <ExternalLink href={authUrl} className="px-0">
                Get auth code
              </ExternalLink>
            ) : isError ? (
              <span className="text-destructive">
                Couldn't load the authorization link.{" "}
                <button type="button" onClick={() => refetch()} className="underline">
                  Retry
                </button>
              </span>
            ) : (
              "Get auth code"
            )}
          </li>
          <li>Paste code</li>
        </ol>
        <ConnectForm />
      </DialogContent>
    </Dialog>
  )
}

function ConnectedView() {
  const disconnectMutation = useDisconnectGog({
    mutation: {
      meta: {
        successToast: "Disconnected from GOG",
        errorToast: "Couldn't disconnect",
        invalidates: [getGetGogStatusQueryKey()],
      },
    },
  })

  return (
    <DisconnectDialogButton
      dialogTitle="Disconnect GOG?"
      dialogDescription="Silo will forget the stored GOG tokens. Imported games are kept."
      onConfirm={() => disconnectMutation.mutate()}
    />
  )
}
