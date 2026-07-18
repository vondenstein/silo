/**
 * Custom fetch mutator used by orval-generated hooks. Returns the parsed
 * response body and throws ApiError on non-2xx, so TanStack Query's
 * `data` / `error` / `isError` work directly on body types.
 */

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly response: Response

  constructor(status: number, detail: string, response: Response) {
    super(detail)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
    this.response = response
  }
}

export async function fetchWithErrors<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)

  if (!response.ok) {
    let detail = ""
    try {
      const body = await response.clone().json()
      // FastAPI's HTTPException returns { detail: string | list | object }
      if (body && typeof body.detail === "string") {
        detail = body.detail
      } else if (Array.isArray(body?.detail)) {
        // Validation errors: [{ loc, msg, … }] → "field: message" lines.
        detail = body.detail
          .map((entry: { loc?: (string | number)[]; msg?: string }) =>
            [entry.loc?.slice(1).join("."), entry.msg].filter(Boolean).join(": "),
          )
          .join("; ")
      } else if (body?.detail) {
        detail = JSON.stringify(body.detail)
      }
    } catch {
      // Response body wasn't JSON.
    }
    // statusText is empty under HTTP/2 — never throw an empty message.
    throw new ApiError(
      response.status,
      detail || response.statusText || `HTTP ${response.status}`,
      response,
    )
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json()
}
