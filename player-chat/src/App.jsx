import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider, RequireAuth } from './auth'
import PortfolioPage from './pages/PortfolioPage'
import AccessGate from './AccessGate'
import PlayerLayout from './layout/PlayerLayout'
import AdminLayout from './layout/AdminLayout'
import TicketsPage from './pages/TicketsPage'
import AccountsPage from './pages/AccountsPage'
import AdminPage from './pages/AdminPage'
import AdminTickets from './pages/AdminTickets'
import RouteMotion from './RouteMotion'

function App() {
  return (
    <AccessGate><AuthProvider>
      <BrowserRouter>
        <RouteMotion />
        <Routes>
          <Route path="/" element={<PortfolioPage />} />
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<AdminPage />} />
            <Route path="tickets" element={<AdminTickets />} />
          </Route>
          <Route element={<PlayerLayout />}>
            <Route path="/chat" element={<RequireAuth>{null}</RequireAuth>} />
            <Route path="/accounts" element={<AccountsPage />} />
            <Route
              path="/tickets"
              element={
                <RequireAuth>
                  <TicketsPage />
                </RequireAuth>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider></AccessGate>
  )
}

export default App
