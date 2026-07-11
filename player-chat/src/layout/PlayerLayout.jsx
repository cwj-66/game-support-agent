import { NavLink, Outlet } from 'react-router-dom'
import './PlayerLayout.css'

function PlayerLayout() {
  return (
    <div className="player-layout">
      <header className="player-header">
        <div className="player-header-inner">
          <h1 className="player-title">游戏客服</h1>
          <nav className="player-nav">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `player-nav-link${isActive ? ' active' : ''}`
              }
            >
              聊天
            </NavLink>
            <NavLink
              to="/tickets"
              className={({ isActive }) =>
                `player-nav-link${isActive ? ' active' : ''}`
              }
            >
              我的工单
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="player-main">
        <Outlet />
      </main>
    </div>
  )
}

export default PlayerLayout
