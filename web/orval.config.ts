import { defineConfig } from "orval"

export default defineConfig({
  silo: {
    input: "../api/openapi.json",
    output: {
      target: "src/lib/api/client.ts",
      schemas: "src/lib/api/model",
      client: "react-query",
      baseUrl: "",
      formatter: "prettier",
      // orval ≥8.20 required: older fetch builders comma-join array query params
      // (FastAPI 422s that background polls swallow silently).
      override: {
        mutator: {
          path: "./src/lib/fetch-mutator.ts",
          name: "fetchWithErrors",
        },
        fetch: {
          includeHttpResponseReturnType: false,
        },
        // Never set useQuery here — 8.20 would force query hooks onto POST
        // endpoints (broken generated code); GETs get query hooks by default.
        query: {
          useSuspenseQuery: true,
          useInfinite: true,
          useSuspenseInfiniteQuery: true,
          useInfiniteQueryParam: "cursor",
        },
      },
    },
  },
})
