export function friendlyJobError(code: string | undefined, message: string | undefined, fallback: string): string {
  if (code === 'interrupted') {
    return 'The server restarted while your file was being processed. Your original file is safe; please try again.'
  }
  return message ?? fallback
}
