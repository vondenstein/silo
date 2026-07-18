import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { useFormContext } from "@/hooks/form-context"

export function SubmitButton({ children }: { children: ReactNode }) {
  const form = useFormContext()
  return (
    <form.Subscribe selector={(state) => state.isSubmitting}>
      {(isSubmitting) => (
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : children}
        </Button>
      )}
    </form.Subscribe>
  )
}
