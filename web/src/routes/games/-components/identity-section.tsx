import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  getGetGameQueryKey,
  searchMetadataSource,
  useListMetadataSources,
  useDeleteGameIdentity,
  useSetGameIdentity,
} from "@/lib/api/client"
import type { GameDetail, SearchCandidateOut } from "@/lib/api/model"
import { SectionHeader } from "@/routes/games/-components/section-header"
import { MagnifyingGlassIcon, XIcon } from "@phosphor-icons/react"
import { useRef, useState } from "react"
import { toast } from "sonner"

export function IdentitySection({ game }: { game: GameDetail }) {
  const { data: sources = [] } = useListMetadataSources()
  const [sourceSlug, setSourceSlug] = useState("")
  const [externalId, setExternalId] = useState("")
  const [query, setQuery] = useState("")
  const [candidates, setCandidates] = useState<SearchCandidateOut[] | null>(null)
  const [searching, setSearching] = useState(false)
  // Bumped per search (and on source change) so a slow earlier response
  // can't overwrite a newer one.
  const searchSeq = useRef(0)

  const setIdentity = useSetGameIdentity({
    mutation: {
      meta: {
        successToast: "Identity set",
        errorToast: "Failed to set identity",
        invalidates: [getGetGameQueryKey(game.id)],
      },
    },
  })
  const removeIdentity = useDeleteGameIdentity({
    mutation: {
      meta: { errorToast: "Failed to remove identity", invalidates: [getGetGameQueryKey(game.id)] },
    },
  })

  const selected = sources.find((source) => source.slug === sourceSlug)

  const add = async () => {
    const external_id = externalId.trim()
    if (!sourceSlug || !external_id) return
    try {
      await setIdentity.mutateAsync({ gameId: game.id, sourceSlug, data: { external_id } })
      setExternalId("")
      setQuery("")
      setCandidates(null)
    } catch {
      // The global MutationCache onError already toasted.
    }
  }

  const remove = (slug: string) => removeIdentity.mutate({ gameId: game.id, sourceSlug: slug })

  const search = async () => {
    const term = query.trim()
    if (!sourceSlug || !term) return
    const seq = ++searchSeq.current
    setSearching(true)
    try {
      const results = await searchMetadataSource(sourceSlug, { q: term })
      if (seq === searchSeq.current) setCandidates(results)
    } catch (error) {
      if (seq === searchSeq.current) {
        toast.error(error instanceof Error ? error.message : "Search failed")
        setCandidates(null)
      }
    } finally {
      if (seq === searchSeq.current) setSearching(false)
    }
  }

  const changeSource = (slug: string) => {
    setSourceSlug(slug)
    // A picked external id and search results don't carry across sources.
    searchSeq.current++
    setCandidates(null)
    setExternalId("")
    setSearching(false)
  }

  return (
    <div className="flex flex-1 flex-col gap-4">
      <SectionHeader
        title="Identity"
        description="Catalog ids linking this game to metadata sources — what Fetch metadata reads."
      />

      {game.external_identities.length > 0 ? (
        <div className="space-y-2">
          {game.external_identities.map((identity) => (
            <div key={identity.source_slug} className="flex items-center gap-2">
              <Badge variant="outline">{identity.source_slug}</Badge>
              <span className="font-mono text-sm">{identity.external_id}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="ml-auto"
                onClick={() => remove(identity.source_slug)}
                disabled={removeIdentity.isPending}
                aria-label={`Remove ${identity.source_slug} identity`}
              >
                <XIcon />
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          No identities yet — without one, metadata can't be fetched.
        </p>
      )}

      <div className="space-y-3 border-t pt-4">
        <Field>
          <FieldLabel htmlFor="identity-source">Source</FieldLabel>
          <Select value={sourceSlug} onValueChange={changeSource}>
            <SelectTrigger id="identity-source" className="w-56">
              <SelectValue placeholder="Choose a source" />
            </SelectTrigger>
            <SelectContent>
              {sources.map((source) => (
                <SelectItem key={source.id} value={source.slug}>
                  {source.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        {selected?.searchable && (
          <div className="space-y-2">
            <div className="flex gap-2">
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    search()
                  }
                }}
                placeholder={`Search ${selected.name} by title…`}
              />
              <Button
                type="button"
                variant="outline"
                onClick={search}
                disabled={searching || !query.trim()}
              >
                <MagnifyingGlassIcon /> {searching ? "Searching…" : "Search"}
              </Button>
            </div>
            {candidates !== null &&
              (candidates.length > 0 ? (
                <div className="divide-y rounded-md border">
                  {candidates.map((candidate) => (
                    <button
                      key={candidate.external_id}
                      type="button"
                      onClick={() => setExternalId(candidate.external_id)}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50"
                    >
                      <span>{candidate.name}</span>
                      {candidate.year != null && (
                        <span className="text-muted-foreground">({candidate.year})</span>
                      )}
                      <span className="ml-auto font-mono text-xs text-muted-foreground">
                        {candidate.external_id}
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No results.</p>
              ))}
          </div>
        )}

        <div className="flex gap-2">
          <Input
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
            placeholder="External id"
            className="font-mono"
          />
          <Button
            type="button"
            onClick={add}
            disabled={!sourceSlug || !externalId.trim() || setIdentity.isPending}
          >
            Set identity
          </Button>
        </div>
      </div>
    </div>
  )
}
