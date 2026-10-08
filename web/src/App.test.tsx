// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import App from './App'

test('renders health status from API', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: 'ok', version: 'test', database: 'ok' }),
    }),
  )
  render(<App />)
  await waitFor(() => {
    expect(screen.getByTestId('health').textContent).toContain('版本 test')
  })
})
