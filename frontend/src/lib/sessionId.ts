const STORAGE_KEY = 'ktru_session_id'

function generateId(): string {
  return crypto.randomUUID().replace(/-/g, '').slice(0, 24)
}

/** Return a stable per-browser session ID, creating one on first visit. */
export function getSessionId(): string {
  if (typeof localStorage === 'undefined') return generateId()
  try {
    let id = localStorage.getItem(STORAGE_KEY)
    if (!id) {
      id = generateId()
      localStorage.setItem(STORAGE_KEY, id)
    }
    return id
  } catch {
    return generateId()
  }
}
