import { MutationCache, QueryClient, type QueryKey } from "@tanstack/react-query"
import { toast } from "sonner"

import { ApiError } from "@/lib/fetch-mutator"

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      successToast?: string
      errorToast?: string | false
      invalidates?: QueryKey[]
    }
  }
}

export const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // A 4xx is conclusive — retrying it just delays the error surfacing.
      retry: (failureCount, error) =>
        failureCount < 3 && !(error instanceof ApiError && error.status < 500),
    },
  },
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      const { errorToast } = mutation.meta ?? {}
      if (errorToast === false) return
      // Consumer string as the headline, server detail as the fine print.
      toast.error(errorToast ?? "Request failed", {
        description: error instanceof ApiError ? error.detail : undefined,
      })
    },
    onSuccess: (_data, _variables, _context, mutation) => {
      const { successToast, invalidates } = mutation.meta ?? {}
      if (successToast) toast.success(successToast)
      if (invalidates) {
        // Returned promise is awaited: the mutation stays pending until the
        // invalidated queries have refetched.
        return Promise.all(
          invalidates.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
        )
      }
    },
  }),
})
