import { startMotion } from './motion-core.js?v=20261005c'

let stop = startMotion()
window.addEventListener('pagehide', () => stop())
window.addEventListener('pageshow', event => {
  if (event.persisted) stop = startMotion()
})
