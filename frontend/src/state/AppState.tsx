import { createContext, useContext, useEffect, useReducer, type Dispatch, type ReactNode } from 'react'
import { buildSearch, parseUrl } from '@/lib/urlState'
import type { Decisions, ProfileResponse, ResultsResponse, UploadResponse } from '@/api/types'

export const STEPS = [
  'Upload',
  'Profile',
  'Suggested fixes',
  'Processing',
  'Results',
  'Downloads',
] as const

export interface AppState {
  step: number // 0-based index into STEPS
  datasetId: string | null
  upload: UploadResponse | null
  profile: ProfileResponse | null
  decisions: Decisions
  jobId: string | null
  jobRunning: boolean
  sheet: string | null
  headerRow: number
  results: ResultsResponse | null
}

export type Action =
  | { type: 'goto'; step: number }
  | { type: 'uploaded'; upload: UploadResponse }
  | { type: 'profile_loaded'; profile: ProfileResponse }
  | { type: 'set_decisions'; decisions: Decisions }
  | { type: 'job_started'; jobId: string; sheet?: string | null; headerRow?: number }
  | { type: 'job_finished' }
  | { type: 'results_loaded'; results: ResultsResponse }
  | { type: 'reset' }

export const emptyDecisions: Decisions = { approved: [], rejected: [], edited: [] }

export const initialState: AppState = {
  step: 0,
  datasetId: null,
  upload: null,
  profile: null,
  decisions: emptyDecisions,
  jobId: null,
  jobRunning: false,
  sheet: null,
  headerRow: 0,
  results: null,
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'goto':
      return { ...state, step: Math.max(0, Math.min(STEPS.length - 1, action.step)) }
    case 'uploaded':
      return { ...initialState, step: 1, datasetId: action.upload.dataset_id, upload: action.upload }
    case 'profile_loaded':
      return { ...state, profile: action.profile, decisions: emptyDecisions, results: null }
    case 'set_decisions':
      return { ...state, decisions: action.decisions }
    case 'job_started':
      return {
        ...state,
        jobId: action.jobId,
        jobRunning: true,
        sheet: action.sheet === undefined ? state.sheet : action.sheet,
        headerRow: action.headerRow ?? state.headerRow,
      }
    case 'job_finished':
      return { ...state, jobRunning: false }
    case 'results_loaded':
      return { ...state, results: action.results }
    case 'reset':
      return initialState
  }
}

/** Rebuilds the state from `?d=&j=&s=` so a reload or reopened link picks up where it was. */
export function initFromUrl(search: string): AppState {
  const u = parseUrl(search)
  if (!u) return initialState
  const step = u.step === 3 && !u.jobId ? 2 : u.step
  const jobRunning = !!u.jobId && (step === 1 || step === 3)
  return { ...initialState, step, datasetId: u.datasetId, jobId: u.jobId, jobRunning }
}

const Ctx = createContext<{ state: AppState; dispatch: Dispatch<Action> } | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, window.location.search, initFromUrl)
  const { step, datasetId, jobId } = state
  useEffect(() => {
    const search = buildSearch({ step, datasetId, jobId })
    if (search !== window.location.search) {
      const { pathname, hash } = window.location
      window.history.replaceState(null, '', `${pathname}${search}${hash}`)
    }
  }, [step, datasetId, jobId])
  return <Ctx.Provider value={{ state, dispatch }}>{children}</Ctx.Provider>
}

export function useAppState() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAppState must be used inside AppStateProvider')
  return ctx
}

