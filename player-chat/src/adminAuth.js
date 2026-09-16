export const REVIEWER_ID = 'admin_001'

export const AUTH_HEADERS = {
  'X-Reviewer-Token': import.meta.env.VITE_REVIEWER_TOKEN || 'dev',
}
