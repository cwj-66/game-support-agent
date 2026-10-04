import { Link, NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Button, message } from 'antd'
import { MessageOutlined, TeamOutlined, FileTextOutlined, AppstoreOutlined, CustomerServiceOutlined, LogoutOutlined } from '@ant-design/icons'
import { useAuth } from '../auth'
import ChatPage from '../pages/ChatPage'
import './PlayerLayout.css'

function PlayerLayout() {
  const { player, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()

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
                to="/chat"
                end
                onClick={requireAccount}
                className={({ isActive }) =>
                  `player-nav-link${isActive ? ' active' : ''}`
                }
              >
                <MessageOutlined aria-hidden="true" /> 聊天
              </NavLink>
              <NavLink
                to="/accounts"
                className={({ isActive }) =>
                  `player-nav-link${isActive ? ' active' : ''}`
                }
              >
                <TeamOutlined aria-hidden="true" /> 测试账号
              </NavLink>
              <NavLink
                to="/tickets"
                onClick={requireAccount}
                className={({ isActive }) =>
                  `player-nav-link${isActive ? ' active' : ''}`
                }
              >
                <FileTextOutlined aria-hidden="true" /> 我的工单
              </NavLink>
            </nav>
          </div>
          <a href="/" className="workbench-entry portfolio-entry"><AppstoreOutlined aria-hidden="true" /> 作品集首页</a>
          <Link to="/admin" target="_blank" rel="noopener noreferrer" className="workbench-entry customer-workbench-entry">
            <CustomerServiceOutlined aria-hidden="true" /> 客服工作台
          </Link>
          <div className="player-user">
            {player ? (
              <>
                <span className="player-user-name">
                  {player.nickname}
                  <em>UID {player.uid}</em>
                </span>
                <Button className="logout-button" size="small" icon={<LogoutOutlined aria-hidden="true" />} onClick={handleLogout}>
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
        {player && <div hidden={pathname !== '/chat'}><ChatPage key={player.uid} /></div>}
        <Outlet />
      </main>
    </div>
  )
}

export default PlayerLayout
