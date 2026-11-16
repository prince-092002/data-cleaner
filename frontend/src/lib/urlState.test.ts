import { describe, expect, it } from 'vitest'
import { buildSearch, parseUrl } from './urlState'

const D = '3f2b8c1e-aaaa-4bbb-8ccc-123456789abc'
const J = '9a8b7c6d-aaaa-4bbb-8ccc-123456789abc'

describe('url state', () => {
  it('writes dataset, job and screen', () => {
    expect(buildSearch({ step: 3, datasetId: D, jobId: J })).toBe(`?d=${D}&j=${J}&s=processing`)
    expect(buildSearch({ step: 4, datasetId: D, jobId: null })).toBe(`?d=${D}&s=results`)
  })

  it('writes nothing on the upload screen or without a dataset', () => {
    expect(buildSearch({ step: 0, datasetId: D, jobId: J })).toBe('')
    expect(buildSearch({ step: 3, datasetId: null, jobId: null })).toBe('')
  })

  it('reads what it wrote', () => {
    expect(parseUrl(`?d=${D}&j=${J}&s=processing`)).toEqual({ datasetId: D, jobId: J, step: 3 })
    expect(parseUrl(`?d=${D}&s=fixes`)).toEqual({ datasetId: D, jobId: null, step: 2 })
  })

  it('defaults to the profile screen when only a dataset is given', () => {
    expect(parseUrl(`?d=${D}`)?.step).toBe(1)
  })

  it('ignores missing, upload or malformed values', () => {
    expect(parseUrl('')).toBeNull()
    expect(parseUrl(`?s=results`)).toBeNull()
    expect(parseUrl(`?d=${D}&s=upload`)).toBeNull()
    expect(parseUrl(`?d=${D}&s=nonsense`)).toBeNull()
    expect(parseUrl('?d=../etc&s=results')).toBeNull()
    expect(parseUrl(`?d=${D}&j=<script>&s=processing`)?.jobId).toBeNull()
  })
})
