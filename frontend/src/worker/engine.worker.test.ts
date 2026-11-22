import { describe, expect, it, vi } from 'vitest'
import { callPython, type Py } from './engine.worker'

describe('callPython', () => {
  it('keeps the upload bytes out of the JSON sent to Python', () => {
    const call = vi.fn(() => '{"ok":true,"result":{}}')
    const writeFile = vi.fn()
    const py = { FS: { writeFile }, globals: { get: () => call } } as unknown as Py
    callPython(py, 'upload', { name: 'a.csv', data: new Uint8Array([1, 2, 3]) }, () => {})
    expect(writeFile).toHaveBeenCalledWith('/tmp/in.bin', new Uint8Array([1, 2, 3]))
    expect(JSON.parse((call.mock.calls[0] as unknown as string[])[1])).toEqual({ name: 'a.csv' })
  })
})
