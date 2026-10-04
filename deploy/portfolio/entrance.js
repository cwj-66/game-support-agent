import { startMotion } from './motion-core.js?v=20261005b'

let stop = startMotion()
window.addEventListener('pagehide', () => stop())
window.addEventListener('pageshow', event => {
  if (event.persisted) stop = startMotion()
})
