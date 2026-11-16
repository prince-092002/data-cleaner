import '@testing-library/jest-dom/vitest'

afterEach(() => window.history.replaceState(null, '', '/')) // the app keeps ids in the URL; do not leak between tests
