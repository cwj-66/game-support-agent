export async function demoFetch(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options })
  if (response.status === 401) {
    const body = await response.clone().json().catch(() => ({}))
    if (body.code === 'demo_access_required') window.dispatchEvent(new Event('demo-access-expired'))
  }
  return response
}
