import type { AssetKind, FieldKey, GameDetail, GamePatch } from "@/lib/api/model"
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"

export type SectionKey = "details" | "identity" | "cover" | "screenshots" | "groups" | "serials"

/** A section's pending changes, gathered by the shell at save time. */
export type Contribution = {
  patch?: GamePatch
  assetPut?: { kind: AssetKind; blobs: string[] }
}

export type SectionState = { dirty: boolean; invalid?: boolean }

type EditSession = {
  locks: ReadonlySet<FieldKey>
  toggleLock: (key: FieldKey) => void
  lockOnChange: (key: FieldKey) => void
  reportState: (key: SectionKey, state: SectionState) => void
  registerCollector: (key: SectionKey, collect: () => Contribution | null) => () => void
}

const EditSessionContext = createContext<EditSession | null>(null)

export const EditSessionProvider = EditSessionContext

/** Section-side hook: report dirty/invalid state and register a save-time collector. */
export function useEditSection(
  key: SectionKey,
  state: SectionState,
  collect: () => Contribution | null,
) {
  const session = useContext(EditSessionContext)
  if (!session) throw new Error("useEditSection requires an EditSessionProvider")
  const { dirty, invalid = false } = state
  useEffect(() => {
    session.reportState(key, { dirty, invalid })
  }, [session, key, dirty, invalid])
  const collectRef = useRef(collect)
  useEffect(() => {
    collectRef.current = collect
  })
  useEffect(() => {
    const unregister = session.registerCollector(key, () => collectRef.current())
    return () => {
      unregister()
      session.reportState(key, { dirty: false })
    }
  }, [session, key])
  return session
}

/** Dialog-wide lock state: pinned desired set diffed against the live server set. */
function useFieldLocks(game: GameDetail) {
  const [desired, setDesired] = useState(() => new Set<FieldKey>(game.locks))
  const server = new Set<FieldKey>(game.locks)
  const toggle = useCallback(
    (key: FieldKey) =>
      setDesired((prev) => {
        const next = new Set(prev)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      }),
    [],
  )
  // Editing a field auto-flips its lock on (never off) — flip it back before save to opt out.
  const lockOnChange = useCallback(
    (key: FieldKey) =>
      setDesired((prev) => {
        if (prev.has(key)) return prev
        const next = new Set(prev)
        next.add(key)
        return next
      }),
    [],
  )
  const toLock = [...desired].filter((key) => !server.has(key))
  const toUnlock = [...server].filter((key) => !desired.has(key))
  return { locks: desired, toggle, lockOnChange, toLock, toUnlock }
}

/** Shell-side hook: owns the lock set, dirty aggregation, and the collector registry. */
export function useEditSessionState(game: GameDetail) {
  const fieldLocks = useFieldLocks(game)
  const [dirtySections, setDirtySections] = useState<ReadonlySet<SectionKey>>(new Set())
  const [invalidSections, setInvalidSections] = useState<ReadonlySet<SectionKey>>(new Set())
  const collectors = useRef(new Map<SectionKey, () => Contribution | null>())

  const reportState = useCallback((key: SectionKey, state: SectionState) => {
    const apply = (dirty: boolean) => (prev: ReadonlySet<SectionKey>) => {
      if (prev.has(key) === dirty) return prev
      const next = new Set(prev)
      if (dirty) next.add(key)
      else next.delete(key)
      return next
    }
    setDirtySections(apply(state.dirty))
    setInvalidSections(apply(state.invalid ?? false))
  }, [])

  const registerCollector = useCallback((key: SectionKey, collect: () => Contribution | null) => {
    collectors.current.set(key, collect)
    return () => {
      collectors.current.delete(key)
    }
  }, [])

  const session = useMemo<EditSession>(
    () => ({
      locks: fieldLocks.locks,
      toggleLock: fieldLocks.toggle,
      lockOnChange: fieldLocks.lockOnChange,
      reportState,
      registerCollector,
    }),
    [fieldLocks.locks, fieldLocks.toggle, fieldLocks.lockOnChange, reportState, registerCollector],
  )

  const collectAll = useCallback(() => {
    const contributions = new Map<SectionKey, Contribution>()
    for (const [key, collect] of collectors.current) {
      const contribution = collect()
      if (contribution) contributions.set(key, contribution)
    }
    return contributions
  }, [])

  return {
    session,
    anyDirty:
      dirtySections.size > 0 || fieldLocks.toLock.length > 0 || fieldLocks.toUnlock.length > 0,
    anyInvalid: invalidSections.size > 0,
    lockOps: { toLock: fieldLocks.toLock, toUnlock: fieldLocks.toUnlock },
    collectAll,
  }
}
