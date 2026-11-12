import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, startProfile, uploadDataset } from '@/api/client'
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
  return { ApiError, uploadDataset: vi.fn(), startProfile: vi.fn() }
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
})
