import {
  getListGamesSuspenseInfiniteQueryOptions,
  getListJobsInfiniteQueryKey,
  getListJobsQueryKey,
  getListJobsSuspenseInfiniteQueryOptions,
  getListLibrariesSuspenseInfiniteQueryOptions,
} from "@/lib/api/client"
import type {
  ListGamesParams,
  ListJobsParams,
  PageGame,
  PageJob,
  PageLibrary,
} from "@/lib/api/model"

export const gameListQueryOptions = (params?: ListGamesParams) =>
  getListGamesSuspenseInfiniteQueryOptions(params, {
    query: {
      initialPageParam: undefined,
      getNextPageParam: (lastPage: PageGame) => lastPage.next_cursor ?? undefined,
    },
  })

export const libraryListQueryOptions = () =>
  getListLibrariesSuspenseInfiniteQueryOptions(undefined, {
    query: {
      initialPageParam: undefined,
      getNextPageParam: (lastPage: PageLibrary) => lastPage.next_cursor ?? undefined,
    },
  })

/** Both job-list key shapes — what a job-spawning mutation invalidates. */
export const JOB_LIST_KEYS = [getListJobsQueryKey(), getListJobsInfiniteQueryKey()]

export const jobListQueryOptions = (params?: ListJobsParams) =>
  getListJobsSuspenseInfiniteQueryOptions(params, {
    query: {
      initialPageParam: undefined,
      getNextPageParam: (lastPage: PageJob) => lastPage.next_cursor ?? undefined,
    },
  })
