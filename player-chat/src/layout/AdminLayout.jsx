import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from 'antd'
import { REVIEWER_ID } from '../adminAuth'
import '../pages/AdminPage.css'

function AdminLayout() {
  const navigate = useNavigate()

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <div className="admin-sidebar-brand">
          <h2>客服工作台</h2>
          <p>已验证 · 完整客服工作台</p>
        </div>
        <nav className="admin-sidebar-nav">
          <NavLink
            to="/admin"
            end
            className={({ isActive }) =>
              `admin-nav-item${isActive ? ' active' : ''}`
            }
          >
            <span className="nav-icon">💬</span>
            待接待会话
          </NavLink>
          <NavLink
            to="/admin/tickets"
            className={({ isActive }) =>
              `admin-nav-item${isActive ? ' active' : ''}`
            }
          >
            <span className="nav-icon">🎫</span>
            工单
          </NavLink>
        </nav>
        <div className="admin-sidebar-footer">
          <div>客服 ID: {REVIEWER_ID}</div>
          <Button
            ghost
            size="small"
            className="admin-exit-btn"
            onClick={() => navigate('/accounts')}
          >
            返回玩家端
          </Button>
        </div>
      </aside>
      <div className="admin-main">
        <Outlet />
      </div>
    </div>
  )
}

export default AdminLayout
