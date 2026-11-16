import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ApiError, getHealth, startProfile, uploadDataset } from '@/api/client'
import type { UploadResponse } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useAppState } from '@/state/AppState'

export const SAMPLES = [
  { file: 'sales_orders_messy.csv', label: 'Sales orders (CSV)' },
  { file: 'customers_messy.xlsx', label: 'Customers (Excel)' },
  { file: 'hr_survey_messy.csv', label: 'HR survey (CSV)' },
]

/** Friendly client-side check only; the server stays the authority. No size check until the server has told us its limit. */
export function validateFile(file: File, maxMb: number | null): string | null {
  const name = file.name.toLowerCase()
  if (!name.endsWith('.csv') && !name.endsWith('.xlsx')) {
    return 'Only .csv and .xlsx files are supported.'
  }
  if (maxMb !== null && file.size > maxMb * 1024 * 1024) {
    return `This file is larger than ${maxMb} MB. Please choose a smaller file.`
  }
  return null
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function messageOf(e: unknown): string {
  if (e instanceof ApiError && e.code === 'file_too_large') {
    return `${e.message} Please choose a smaller file.`
  }
  if (e instanceof ApiError) return e.message
  return 'Something went wrong. Please try again.'
}

export function UploadScreen() {
  const { dispatch } = useAppState()
  const inputRef = useRef<HTMLInputElement>(null)
  const [upload, setUpload] = useState<UploadResponse | null>(null)
  const [sheetIdx, setSheetIdx] = useState(0)
  const [headerRow, setHeaderRow] = useState(0)
  const [busy, setBusy] = useState<null | 'upload' | 'profile'>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [maxMb, setMaxMb] = useState<number | null>(null)

  useEffect(() => {
    let live = true
    getHealth()
      .then((h) => {
        if (live && h && h.max_upload_mb > 0) setMaxMb(h.max_upload_mb)
      })
      .catch(() => {})                // keep the default; the server still enforces its limit
    return () => {
      live = false
    }
  }, [])

  const sheet = upload?.sheets[sheetIdx] ?? null

  async function doUpload(file: File) {
    setError(null)
    const problem = validateFile(file, maxMb)
    if (problem) {
      setError(problem)
      return
    }
    setBusy('upload')
    try {
      const res = await uploadDataset(file)
      setUpload(res)
      setSheetIdx(0)
      setHeaderRow(res.sheets[0]?.detected_header_row ?? 0)
    } catch (e) {
      setUpload(null)
      setError(messageOf(e))
    } finally {
      setBusy(null)
    }
  }

  async function trySample(name: string) {
    setError(null)
    setBusy('upload')
    let blob: Blob
    try {
      const res = await fetch(`/samples/${name}`)
      if (!res.ok) throw new Error('sample')
      blob = await res.blob()
    } catch {
      setBusy(null)
      setError('Could not load the sample file.')
      return
    }
    await doUpload(new File([blob], name))
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (busy) return
    const f = e.dataTransfer.files?.[0]
    if (f) void doUpload(f)
  }

  function changeSheet(name: string | null) {
    if (!upload || name === null) return
    const idx = upload.sheets.findIndex((s) => s.name === name)
    if (idx < 0) return
    setSheetIdx(idx)
    setHeaderRow(upload.sheets[idx].detected_header_row)
  }

  async function onContinue() {
    if (!upload || !sheet) return
    setError(null)
    setBusy('profile')
    try {
      const job = await startProfile(upload.dataset_id, { sheet: sheet.name, header_row: headerRow })
      dispatch({ type: 'uploaded', upload })
      dispatch({ type: 'job_started', jobId: job.job_id, sheet: sheet.name, headerRow })
    } catch (e) {
      setError(messageOf(e))
      setBusy(null)
    }
  }

  const disabled = busy !== null

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Upload your file</h2>
        </CardTitle>
        <CardDescription>
          Choose a CSV or Excel (.xlsx) file{maxMb !== null && `, ${maxMb} MB or smaller`}.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <p className="text-sm text-slate-700">Files are deleted after 24 hours. Do not upload sensitive data.</p>
        <div
          data-testid="dropzone"
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-6 text-center sm:p-10 ${
            dragging ? 'border-blue-600 bg-blue-50' : 'border-slate-300 bg-white'
          }`}
        >
          <p className="text-sm text-slate-700">Drag and drop a file here, or</p>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx"
            className="sr-only"
            tabIndex={-1}
            aria-label="Choose a CSV or Excel file"
            disabled={disabled}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void doUpload(f)
              e.target.value = ''
            }}
          />
          <Button type="button" disabled={disabled} onClick={() => inputRef.current?.click()}>
            Browse files
          </Button>
          <div className="flex flex-wrap items-center justify-center gap-2" role="group" aria-label="Sample files">
            <span className="text-sm text-slate-700">Or try a sample file:</span>
            {SAMPLES.map((s) => (
              <Button
                key={s.file}
                type="button"
                variant="outline"
                size="sm"
                disabled={disabled}
                onClick={() => void trySample(s.file)}
              >
                {s.label}
              </Button>
            ))}
          </div>
        </div>

        <div aria-live="polite" className="text-sm">
          {busy === 'upload' && <p className="text-slate-700">Uploading and reading your file...</p>}
          {busy === 'profile' && <p className="text-slate-700">Starting analysis...</p>}
          {error && (
            <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-red-800">
              {error}
            </p>
          )}
        </div>

        {upload && sheet && (
          <section className="flex min-w-0 flex-col gap-4" aria-label="Uploaded file details">
            <p className="break-words text-sm">
              <span className="break-all font-medium" title={upload.filename}>{upload.filename}</span>{' '}
              <span className="text-slate-600">({formatSize(upload.size_bytes)})</span>
            </p>

            {upload.sheets.length > 1 && (
              <div className="flex max-w-sm flex-col gap-2">
                <Label htmlFor="sheet-select">Sheet</Label>
                <Select
                  value={sheet.name ?? ''}
                  onValueChange={(v) => changeSheet(v as string | null)}
                  disabled={disabled}
                >
                  <SelectTrigger id="sheet-select" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {upload.sheets.map((s) => (
                      <SelectItem key={s.name} value={s.name ?? ''}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <fieldset className="min-w-0">
              <legend className="text-sm font-medium">Which row holds the column names?</legend>
              <p className="mb-2 text-sm text-slate-600">
                We detected Row {sheet.detected_header_row + 1}. Pick a different row if that is wrong.
              </p>
              <div className="overflow-x-auto rounded border">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Preview of the first {sheet.preview.length} rows</caption>
                  <tbody>
                    {sheet.preview.map((row, i) => {
                      const selected = i === headerRow
                      return (
                        <tr
                          key={i}
                          data-selected={selected}
                          className={selected ? 'bg-blue-50 font-medium' : i % 2 ? 'bg-slate-50' : ''}
                        >
                          <th scope="row" className="whitespace-nowrap p-2 font-normal">
                            <label className="flex cursor-pointer items-center gap-2">
                              <input
                                type="radio"
                                name="header-row"
                                className="size-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
                                checked={selected}
                                disabled={disabled}
                                onChange={() => setHeaderRow(i)}
                              />
                              <span>Row {i + 1}</span>
                            </label>
                          </th>
                          {row.map((c, j) => (
                            <td key={j} className="max-w-48 truncate whitespace-nowrap p-2" title={c}>
                              {c}
                            </td>
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </fieldset>

            <div>
              <Button type="button" disabled={disabled} onClick={() => void onContinue()}>
                Continue
              </Button>
            </div>
          </section>
        )}
      </CardContent>
    </Card>
  )
}
