import { GlowingBadge } from "@/components/unlumen-ui/glowing-badge"

export function ConnectionBadge({
  isLoading,
  isError,
  connected,
  disconnectedLabel = "Disconnected",
}: {
  isLoading: boolean
  isError: boolean
  connected: boolean | undefined
  disconnectedLabel?: string
}) {
  if (isLoading) return <GlowingBadge variant="neutral">Loading</GlowingBadge>
  // A failed status read is not "disconnected" — don't invite a needless re-auth.
  if (isError)
    return (
      <GlowingBadge variant="neutral" pulse={false}>
        Unknown
      </GlowingBadge>
    )
  if (connected) return <GlowingBadge variant="success">Connected</GlowingBadge>
  return (
    <GlowingBadge variant="error" pulse={false}>
      {disconnectedLabel}
    </GlowingBadge>
  )
}
