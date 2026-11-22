import { useState } from 'react'
import { ApiError, downloadUrl, prepareExcel, startDownload } from '@/api/client'
import type { DownloadName } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAppState } from '@/state/AppState'

const FILES: { name: DownloadName; description: string }[] = [
  { name: 'clean.csv', description: 'Your cleaned data as a CSV file. Opens in any spreadsheet or database tool.' },
  {
    name: 'clean.xlsx',
    description:
      'Your cleaned data as an Excel workbook. It is made when you first ask for it, which can take a moment for big files.',
  },
  { name: 'report.html', description: 'A readable cleaning report with quality scores and a summary of what changed.' },
  { name: 'recipe.yaml', description: 'A reusable recipe of the cleaning steps, so the same fixes can be repeated on similar files.' },
  { name: 'changelog.csv', description: 'Every changed cell, with its old and new value, the rule used and whether it was automatic or approved.' },
]

const linkClass =
  'inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2'

export function DownloadsScreen() {
  const { state, dispatch } = useAppState()
  const { datasetId, upload } = state
  const [excel, setExcel] = useState<'idle' | 'preparing'>('idle')
  const [excelError, setExcelError] = useState<string | null>(null)

  async function downloadExcel() {
    if (!datasetId) return
    setExcel('preparing')
    setExcelError(null)
    try {
      await prepareExcel(datasetId)
      startDownload(downloadUrl(datasetId, 'clean.xlsx'))
    } catch (e) {
      setExcelError(
        e instanceof ApiError
          ? e.message
          : 'The Excel file could not be built. The other files are still available.',
      )
    } finally {
      setExcel('idle')
    }
  }

  if (!datasetId) {
    return (
      <Card>
        <CardContent className="space-y-4 pt-6">
          <p>Nothing to download yet.</p>
          <Button onClick={() => dispatch({ type: 'reset' })}>Back to upload</Button>
        </CardContent>
      </Card>
    )
  }

  // Same names the server sends: the upload's name without its extension, then _clean.csv, _report.html and so on.
  const stem = (upload?.filename ?? '').replace(/\.[^.]*$/, '') || 'data'
  const expires = upload?.expires_at ? new Date(upload.expires_at) : null
  const expiresText = expires && !isNaN(expires.getTime()) ? expires.toLocaleString() : null

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Downloads</h2>
      <p className="text-sm text-slate-700">
        Files are deleted 24 hours after upload{expiresText ? ` (expires ${expiresText})` : ''}.
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {FILES.map((f) => (
          <Card key={f.name} data-testid="download-card">
            <CardHeader>
              <CardTitle className="text-base">{f.name}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-slate-700">{f.description}</p>
              <div className="flex flex-wrap gap-2">
                {f.name === 'clean.xlsx' ? (
                  <button
                    type="button"
                    onClick={downloadExcel}
                    disabled={excel === 'preparing'}
                    className={`${linkClass} bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-60`}
                    aria-label={`Download ${f.name}`}
                  >
                    {excel === 'preparing' ? 'Preparing…' : 'Download'}
                  </button>
                ) : (
                  <a
                    href={downloadUrl(datasetId, f.name)}
                    download={`${stem}_${f.name}`}
                    className={`${linkClass} bg-blue-600 text-white hover:bg-blue-700`}
                    aria-label={`Download ${f.name}`}
                  >
                    Download
                  </a>
                )}
                {f.name === 'report.html' && (
                  <a
                    href={downloadUrl(datasetId, f.name)}
                    target="_blank"
                    rel="noopener"
                    className={`${linkClass} border border-slate-300 bg-white hover:bg-slate-100`}
                  >
                    Open in new tab
                  </a>
                )}
              </div>
              {f.name === 'clean.xlsx' && excel === 'preparing' && (
                <p role="status" className="text-sm text-slate-700">
                  Preparing your Excel file… The download starts by itself when it is ready.
                </p>
              )}
              {f.name === 'clean.xlsx' && excelError && (
                <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-900">
                  {excelError}
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="outline" onClick={() => dispatch({ type: 'goto', step: 4 })}>
          Back to results
        </Button>
        <Button onClick={() => dispatch({ type: 'reset' })}>Clean another file</Button>
      </div>
    </div>
  )
}
