import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, prepareExcel, startDownload } from '@/api/client'
import type { UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { DownloadsScreen } from './DownloadsScreen'

vi.mock('@/api/client', async (original) => {
  const real = await original<typeof import('@/api/client')>()
  return { ...real, prepareExcel: vi.fn(), startDownload: vi.fn() }
})

function Seed() {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload: { dataset_id: 'd1', expires_at: '2030-01-02T03:04:05Z' } as UploadResponse })
    setReady(true)
  }, [dispatch])
  return ready ? <DownloadsScreen /> : null
}
const setup = () =>
  render(
    <AppStateProvider>
      <Seed />
    </AppStateProvider>,
  )
const excelButton = () => screen.getByRole('button', { name: 'Download clean.xlsx' })

beforeEach(() => {
  vi.mocked(prepareExcel).mockReset()
  vi.mocked(startDownload).mockReset()
})

describe('DownloadsScreen', () => {
  it('renders five cards; four files are plain download links', () => {
    setup()
    expect(screen.getAllByTestId('download-card')).toHaveLength(5)
    for (const n of ['clean.csv', 'report.html', 'recipe.yaml', 'changelog.csv']) {
      const a = screen.getByRole('link', { name: `Download ${n}` })
      expect(a.getAttribute('href')).toBe(`/api/datasets/d1/downloads/${n}`)
      expect(a.hasAttribute('download')).toBe(true)
    }
    expect(excelButton()).toBeEnabled()
    const open = screen.getByRole('link', { name: 'Open in new tab' })
    expect(open.getAttribute('target')).toBe('_blank')
    expect(open.getAttribute('rel')).toBe('noopener')
    expect(screen.getByText(/24 hours after upload \(expires/)).toBeTruthy()
  })

  it('shows "Preparing your Excel file" and then starts the download', async () => {
    let finish: (v: { ready: boolean }) => void = () => {}
    vi.mocked(prepareExcel).mockReturnValue(new Promise((resolve) => (finish = resolve)))
    const u = userEvent.setup()
    setup()
    await u.click(excelButton())
    expect(screen.getByRole('status')).toHaveTextContent('Preparing your Excel file')
    expect(excelButton()).toBeDisabled()
    expect(startDownload).not.toHaveBeenCalled()
    finish({ ready: true })
    await waitFor(() => expect(startDownload).toHaveBeenCalledWith('/api/datasets/d1/downloads/clean.xlsx'))
    expect(excelButton()).toBeEnabled()
    expect(screen.queryByText(/Preparing your Excel file/)).not.toBeInTheDocument()
  })

  it('an Excel failure shows a message and leaves the other downloads usable', async () => {
    vi.mocked(prepareExcel).mockRejectedValue(
      new ApiError(500, 'excel_failed', 'The Excel file could not be built. The CSV file and the report are still available.'),
    )
    const u = userEvent.setup()
    setup()
    await u.click(excelButton())
    expect(await screen.findByRole('alert')).toHaveTextContent('The Excel file could not be built.')
    expect(startDownload).not.toHaveBeenCalled()
    expect(excelButton()).toBeEnabled()
    expect(screen.getByRole('link', { name: 'Download clean.csv' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download report.html' })).toBeInTheDocument()
  })
})
