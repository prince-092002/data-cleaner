import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getHealth, startProfile, uploadDataset } from '@/api/client'
import type { UploadResponse } from '@/api/types'
import { AppStateProvider } from '@/state/AppState'
import { UploadScreen } from './UploadScreen'

vi.mock('@/api/client', () => {
  class ApiError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
    }
  }
  return { ApiError, uploadDataset: vi.fn(), startProfile: vi.fn(), getHealth: vi.fn() }
})

const rows = (n: number) => Array.from({ length: n }, (_, i) => [`h${i}`, `v${i}`])
const xlsx: UploadResponse = {
  dataset_id: 'd1',
  filename: 'book.xlsx',
  file_type: 'xlsx',
  size_bytes: 2048,
  expires_at: 'x',
  sheets: [
    { name: 'A', row_count_estimate: 5, detected_header_row: 0, preview: rows(10) },
    { name: 'B', row_count_estimate: 5, detected_header_row: 2, preview: rows(10) },
  ],
}

function setup() {
  render(
    <AppStateProvider>
      <UploadScreen />
    </AppStateProvider>,
  )
  return userEvent.setup({ applyAccept: false })
}
const input = () => screen.getByLabelText('Choose a CSV or Excel file') as HTMLInputElement

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(getHealth).mockResolvedValue({ status: 'ok', max_upload_mb: 50 })
})

describe('UploadScreen', () => {
  it('rejects wrong type client-side', async () => {
    const user = setup()
    await user.upload(input(), new File(['x'], 'a.pdf'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only .csv and .xlsx')
    expect(uploadDataset).not.toHaveBeenCalled()
  })

  it('rejects files over 50 MB', async () => {
    const user = setup()
    const big = new File(['x'], 'big.csv')
    Object.defineProperty(big, 'size', { value: 51 * 1024 * 1024 })
    await user.upload(input(), big)
    expect(await screen.findByRole('alert')).toHaveTextContent('50 MB')
    expect(uploadDataset).not.toHaveBeenCalled()
  })

  it('uses the upload limit the server reports', async () => {
    vi.mocked(getHealth).mockResolvedValue({ status: 'ok', max_upload_mb: 4 })
    const user = setup()
    expect(await screen.findByText(/4 MB or smaller/)).toBeInTheDocument()
    const big = new File(['x'], 'big.csv')
    Object.defineProperty(big, 'size', { value: 5 * 1024 * 1024 })
    await user.upload(input(), big)
    expect(await screen.findByRole('alert')).toHaveTextContent('larger than 4 MB')
    expect(uploadDataset).not.toHaveBeenCalled()
  })

  it('explains a server-side size rejection', async () => {
    vi.mocked(uploadDataset).mockRejectedValue(
      new ApiError(413, 'file_too_large', 'Files must be 4 MB or smaller.'),
    )
    const user = setup()
    await user.upload(input(), new File(['x'], 'a.csv'))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Files must be 4 MB or smaller.')
    expect(alert).toHaveTextContent('Please choose a smaller file')
  })

  it('shows the same 4 MB message when the host rejects the body with its own non-JSON 413', async () => {
    vi.mocked(getHealth).mockResolvedValue({ status: 'ok', max_upload_mb: 4 })
    vi.mocked(uploadDataset).mockRejectedValue(
      new ApiError(413, 'internal_error', 'This file is too large. Please choose a smaller file.'),
    )
    const user = setup()
    await screen.findByText(/4 MB or smaller/)
    await user.upload(input(), new File(['x'], 'a.csv'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Files must be 4 MB or smaller. Please choose a smaller file.')
  })

  it('shows server error messages', async () => {
    vi.mocked(uploadDataset).mockRejectedValue(new ApiError(422, 'unreadable_file', 'File is empty.'))
    const user = setup()
    await user.upload(input(), new File(['x'], 'a.csv'))
    expect(await screen.findByRole('alert')).toHaveTextContent('File is empty.')
  })

  it('sheet switch resets header row, and Continue sends the choice', async () => {
    vi.mocked(uploadDataset).mockResolvedValue(xlsx)
    vi.mocked(startProfile).mockResolvedValue({ job_id: 'j1' })
    const user = setup()
    await user.upload(input(), new File(['x'], 'book.xlsx'))
    expect(await screen.findByText('book.xlsx')).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: 'Row 4' }))
    expect(screen.getByRole('radio', { name: 'Row 4' })).toBeChecked()

    await user.click(screen.getByRole('combobox', { name: 'Sheet' }))
    await user.click(await screen.findByRole('option', { name: 'B' }))
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Row 3' })).toBeChecked())

    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(startProfile).toHaveBeenCalledWith('d1', { sheet: 'B', header_row: 2 }))
  })

  it('sample button uploads the fetched file', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['a,b']) }))
    vi.mocked(uploadDataset).mockResolvedValue({
      ...xlsx,
      file_type: 'csv',
      filename: 'sales_orders_messy.csv',
      sheets: [{ name: null, row_count_estimate: 3, detected_header_row: 0, preview: rows(3) }],
    })
    const user = setup()
    await user.click(screen.getByRole('button', { name: 'Sales orders (CSV)' }))
    await waitFor(() => expect(uploadDataset).toHaveBeenCalledTimes(1))
    expect((vi.mocked(uploadDataset).mock.calls[0][0] as File).name).toBe('sales_orders_messy.csv')
    expect(screen.queryByRole('combobox', { name: 'Sheet' })).not.toBeInTheDocument()
  })

  it('tells people files are deleted after 24 hours', () => {
    setup()
    expect(screen.getByText('Files are deleted after 24 hours. Do not upload sensitive data.')).toBeInTheDocument()
  })

  it('does not guess a size limit when the server cannot be reached', async () => {
    vi.mocked(getHealth).mockRejectedValue(new Error('down'))
    const user = setup()
    expect(screen.queryByText(/MB or smaller/)).not.toBeInTheDocument()
    const big = new File(['x'], 'big.csv')
    Object.defineProperty(big, 'size', { value: 60 * 1024 * 1024 })
    vi.mocked(uploadDataset).mockResolvedValue({ ...xlsx, file_type: 'csv', sheets: [xlsx.sheets[0]] })
    await user.upload(input(), big)
    await waitFor(() => expect(uploadDataset).toHaveBeenCalledTimes(1))
  })

  it.each([
    [429, 'too_many_jobs', 'Too many files have been processed today. Please try again tomorrow.'],
    [503, 'storage_full', 'The demo is full right now. Please try again tomorrow.'],
  ])('shows the server message for %i on upload', async (status, code, message) => {
    vi.mocked(uploadDataset).mockRejectedValue(new ApiError(status, code, message))
    const user = setup()
    await user.upload(input(), new File(['x'], 'a.csv'))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('shows the daily cap message when starting the profile', async () => {
    vi.mocked(uploadDataset).mockResolvedValue(xlsx)
    vi.mocked(startProfile).mockRejectedValue(new ApiError(429, 'too_many_jobs', 'The daily limit is reached. Try again tomorrow.'))
    const user = setup()
    await user.upload(input(), new File(['x'], 'book.xlsx'))
    await user.click(await screen.findByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The daily limit is reached. Try again tomorrow.')
  })
})
