export const EXPIRED_MESSAGE = 'This result has expired. Please upload the file again.'

const CODE_FALLBACKS: Record<string, string> = {
  job_timeout: 'This file took too long to process. Try a smaller file.',
  superseded: 'A newer job replaced this one. Please start again.',
}

/** The server says 404 for an unknown or expired dataset, job, profile or result. */
export function isNotFound(e: unknown): boolean {
  return (e as { status?: number } | null)?.status === 404
}

export function friendlyJobError(code: string | undefined, message: string | undefined, fallback: string): string {
  if (code === 'interrupted') {
    return 'The server restarted while your file was being processed. Your original file is safe; please try again.'
  }
  if (code === 'expired') return EXPIRED_MESSAGE
  return message ?? (code ? CODE_FALLBACKS[code] : undefined) ?? fallback
}
