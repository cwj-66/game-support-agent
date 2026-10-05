// Animate visible content without hiding it or remounting live chat sessions.
export function startMotion(root = document) {
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
  if (preference.matches || !window.IntersectionObserver || !Element.prototype.animate) return () => {}
  const seen = new WeakSet()
  const watched = new WeakSet()
  const animations = new Set()
  const selector = '.agent-section,.agent-summary,.feature-item,.explain-panel,.evidence-card,.react-diagram,.tech-wrap,.capacity-numbers,.protection-grid article,.try-path article,.agent-bottom,.hero,.home-detail,.experience-page-title,.slide-heading,.slide-summary,.editorial-grid,.story-section,.agent-flow,.experience-points,.evidence,.outcome-grid,.reflection-grid,.account-card,.tickets-header,.ticket-card'
  const play = (element, distance = 24, delay = 0) => {
    const animation = element.animate([
      { transform: `translateY(${distance}px)` },
      { transform: 'translateY(0)' },
    ], { duration: 450, delay, fill: 'backwards', easing: 'cubic-bezier(.22,1,.36,1)' })
    animations.add(animation)
    animation.finished.then(() => animations.delete(animation), () => animations.delete(animation))
  }
  const observer = new IntersectionObserver(entries => {
    let order = 0
    for (const entry of entries) {
      if (!entry.isIntersecting || seen.has(entry.target)) continue
      seen.add(entry.target)
      play(entry.target, 24, Math.min(order++ * 60, 180))
      observer.unobserve(entry.target)
    }
  }, { threshold: 0.08, rootMargin: '0px 0px -24px 0px' })
  const scan = () => {
    root.querySelectorAll(selector).forEach(element => {
      // Section/card nesting uses one animation to avoid multiplying movement.
      if (element.parentElement?.closest(selector) || watched.has(element)) return
      watched.add(element)
      observer.observe(element)
    })
  }
  const surface = root.querySelector('.player-main,.admin-main,main,.login-main')
  if (surface) play(surface, 12)
  scan()
  let frame = 0
  const mutations = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes' && !record.target.hidden) {
        record.target.querySelectorAll(selector).forEach(element => {
          seen.delete(element)
          if (watched.has(element)) observer.observe(element)
        })
      }
    }
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; scan() })
  })
  mutations.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['hidden'] })
  const stop = () => {
    observer.disconnect()
    mutations.disconnect()
    cancelAnimationFrame(frame)
    animations.forEach(animation => animation.cancel())
    animations.clear()
  }
  const onPreference = () => { if (preference.matches) stop() }
  preference.addEventListener('change', onPreference)
  return () => { stop(); preference.removeEventListener('change', onPreference) }
}
