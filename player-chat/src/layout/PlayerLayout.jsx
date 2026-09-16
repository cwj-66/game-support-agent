import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button, message } from 'antd'
import { useAuth } from '../auth'
import './PlayerLayout.css'

function PlayerLayout() {
  const { player, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/accounts')
  }

  const requireAccount = (event) => {
    if (player) return
    event.preventDefault()
    message.warning({
      content: '请先选择一个测试账号',
      key: 'need-account',
    })
  }

  return (
    <div className="player-layout">
      <header className="player-header">
        <div className="player-header-inner">
          <div className="player-brand-block">
            <h1 className="player-title">游戏客服</h1>
            <nav className="player-nav">
              <NavLink
                to="/"
                end
                onClick={requireAccount}
                className={({ isActive }) =>
                  `player-nav-link${isActive ? ' active' : ''}`
                }
              >
                聊天
              </NavLink>
              <NavLink
                to="/accounts"
                className={({ isActive }) =>
                  `player-nav-link${isActive ? ' active' : ''}`
                }
              >
                测试账号
              </NavLink>
              <NavLink
                to="/tickets"
                onClick={requireAccount}
                className={({ isActive }) =>
                  `player-nav-link${isActive ? ' active' : ''}`
                }
              >
                我的工单
              </NavLink>
            </nav>
          </div>
          <Link to="/admin" className="workbench-entry">
            客服工作台
          </Link>
          <div className="player-user">
            {player ? (
              <>
                <span className="player-user-name">
                  {player.nickname}
                  <em>UID {player.uid}</em>
                </span>
                <Button size="small" ghost onClick={handleLogout}>
                  退出
                </Button>
              </>
            ) : (
              <span className="player-user-hint">请选择测试账号</span>
            )}
          </div>
        </div>
      </header>
      <main className="player-main">
        <Outlet />
      </main>
    </div>
  )
}

export default PlayerLayout
