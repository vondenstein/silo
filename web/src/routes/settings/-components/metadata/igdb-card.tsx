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
  getGetIgdbStatusQueryKey,
  useConnectIgdb,
  useDisconnectIgdb,
  useGetIgdbStatus,
} from "@/lib/api/client"
import { ConnectionBadge } from "@/routes/settings/-components/connection-badge"
import { DisconnectDialogButton } from "@/routes/settings/-components/disconnect-dialog-button"
import { SettingsCard } from "@/routes/settings/-components/settings-card"
import * as z from "zod"

export function IgdbCard() {
  const { data: status, isLoading, isError, refetch } = useGetIgdbStatus()

  return (
    <SettingsCard
      title="IGDB"
      description={
        <>
          Rich metadata and artwork from{" "}
          <ExternalLink href="https://www.igdb.com">IGDB</ExternalLink>. Requires{" "}
          <ExternalLink href="https://dev.twitch.tv/console/apps">
            Twitch app credentials
          </ExternalLink>
          .
        </>
      }
      action={
        <ConnectionBadge
          isLoading={isLoading}
          isError={isError}
          connected={status?.connected}
          disconnectedLabel="Not connected"
        />
      }
    >
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <div className="flex items-center gap-3">
          <p className="text-sm text-muted-foreground">Couldn't load the IGDB status.</p>
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
  const connectMutation = useConnectIgdb({
    mutation: {
      meta: {
        successToast: "Connected to IGDB",
        errorToast: "Twitch rejected the credentials",
        invalidates: [getGetIgdbStatusQueryKey()],
      },
    },
  })

  const form = useAppForm({
    defaultValues: { client_id: "", client_secret: "" },
    validators: {
      onSubmit: z.object({
        client_id: z.string().trim().min(1, "Required"),
        client_secret: z.string().trim().min(1, "Required"),
      }),
    },
    onSubmit: async ({ value }) => {
      try {
        // Awaited so the submit button stays disabled through the exchange.
        await connectMutation.mutateAsync({
          data: { client_id: value.client_id.trim(), client_secret: value.client_secret.trim() },
        })
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
      <form.AppField name="client_id">{(f) => <f.TextField label="Client ID" />}</form.AppField>
      <form.AppField name="client_secret">
        {(f) => <f.TextField label="Client Secret" type="password" />}
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
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button>Connect</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect IGDB</DialogTitle>
          <DialogDescription>
            IGDB uses Twitch's authentication. Create a Twitch application to get credentials.
          </DialogDescription>
        </DialogHeader>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            Sign in at{" "}
            <ExternalLink href="https://dev.twitch.tv/console/apps" className="px-0">
              dev.twitch.tv
            </ExternalLink>
          </li>
          <li>Create an application (any name; OAuth redirect can be http://localhost)</li>
          <li>Copy the Client ID and generate a Client Secret</li>
        </ol>
        <ConnectForm />
      </DialogContent>
    </Dialog>
  )
}

function ConnectedView() {
  const disconnectMutation = useDisconnectIgdb({
    mutation: {
      meta: {
        successToast: "Disconnected from IGDB",
        errorToast: "Couldn't disconnect",
        invalidates: [getGetIgdbStatusQueryKey()],
      },
    },
  })

  return (
    <DisconnectDialogButton
      dialogTitle="Disconnect IGDB?"
      dialogDescription="Silo will forget the stored Twitch credentials. Existing IGDB metadata stays on your games."
      onConfirm={() => disconnectMutation.mutate()}
    />
  )
}
