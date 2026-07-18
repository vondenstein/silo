import { createFileRoute } from "@tanstack/react-router"
import { BarnIcon } from "@phosphor-icons/react"

export const Route = createFileRoute("/")({
  component: HomeComponent,
  staticData: {
    title: "Home",
  },
})

function HomeComponent() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4">
      <BarnIcon className="size-12 text-muted-foreground" weight="duotone" />
      <h1 className="text-4xl font-semibold tracking-tight">Silo</h1>
      <p className="text-sm text-muted-foreground">Your self-hosted game library.</p>
    </div>
  )
}
