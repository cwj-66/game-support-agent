import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { startMotion } from './motion'

export default function RouteMotion() {
  const { pathname } = useLocation()
  useEffect(() => startMotion(document.getElementById('root')), [pathname])
  return null
}
