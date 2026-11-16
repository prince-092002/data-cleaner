import type {
  ApiErrorBody,
  Decisions,
  JobCreated,
  JobStatus,
  ProfileRequest,
  ProfileResponse,
  ResultsQuery,
  ResultsResponse,
  UploadResponse,
} from './types'

const BASE = '/api'

// Used only when the server sends no message of its own.
const STATUS_FALLBACKS: Record<number, string> = {
  413: 'This file is too large. Please choose a smaller file.',
  429: 'Too many files have been processed today. Please try again tomorrow.',
  503: 'The demo is full right now. Please try again tomorrow.',
}

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, init)
  } catch {
    throw new ApiError(
      0,
      'network_error',
      'Could not reach the server. Check your connection and try again.',
    )
  }
  if (!res.ok) {
    let code = 'internal_error'
    let message = STATUS_FALLBACKS[res.status] ?? `The server returned an error (${res.status}).`
    try {
      const body = (await res.json()) as Partial<ApiErrorBody>
      if (body.error?.code) code = body.error.code
      if (body.error?.message) message = body.error.message
    } catch {
      // body was not JSON; keep the generic message
    }
    throw new ApiError(res.status, code, message)
  }
  return (await res.json()) as T
}

function jsonPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

const enc = encodeURIComponent

/** GET /api/health: also tells the website the upload limit. */
export function getHealth(): Promise<{ status: string; max_upload_mb: number }> {
  return request('/health')
}

export function uploadDataset(file: File): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  return request<UploadResponse>('/datasets', { method: 'POST', body: form })
}

export function startProfile(datasetId: string, body: ProfileRequest = {}): Promise<JobCreated> {
  return jsonPost<JobCreated>(`/datasets/${enc(datasetId)}/profile`, body)
}

export function getJob(jobId: string): Promise<JobStatus> {
  return request<JobStatus>(`/jobs/${enc(jobId)}`)
}

export function getProfile(datasetId: string): Promise<ProfileResponse> {
  return request<ProfileResponse>(`/datasets/${enc(datasetId)}/profile`)
}

export function startClean(datasetId: string, decisions: Decisions): Promise<JobCreated> {
  return jsonPost<JobCreated>(`/datasets/${enc(datasetId)}/clean`, decisions)
}

export function resultsQueryString(q: ResultsQuery = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(q)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  }
  const s = params.toString()
  return s ? `?${s}` : ''
}

export function getResults(datasetId: string, query: ResultsQuery = {}): Promise<ResultsResponse> {
  return request<ResultsResponse>(`/datasets/${enc(datasetId)}/results${resultsQueryString(query)}`)
}

/** Builds clean.xlsx on the server if it is not there yet (it is made on first download). */
export function prepareExcel(datasetId: string): Promise<{ ready: boolean }> {
  return request(`/datasets/${enc(datasetId)}/downloads/clean.xlsx/prepare`, { method: 'POST' })
}

/** Starts a normal browser download (streamed by the browser, not held in page memory). */
export function startDownload(url: string): void {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  a.remove()
}

export function downloadUrl(datasetId: string, name: string): string {
  return `${BASE}/datasets/${enc(datasetId)}/downloads/${enc(name)}`
}
