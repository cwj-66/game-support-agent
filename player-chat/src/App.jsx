import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider, RequireAuth, useAuth } from './auth'
import PlayerLayout from './layout/PlayerLayout'
import AdminLayout from './layout/AdminLayout'
import ChatPage from './pages/ChatPage'
import TicketsPage from './pages/TicketsPage'
import AccountsPage from './pages/AccountsPage'
import AdminPage from './pages/AdminPage'
import AdminTickets from './pages/AdminTickets'

function ChatRoute() {
  const { player } = useAuth()
  return (
    <RequireAuth>
      <ChatPage key={player?.uid} />
    </RequireAuth>
  )
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<AdminPage />} />
            <Route path="tickets" element={<AdminTickets />} />
          </Route>
          <Route element={<PlayerLayout />}>
            <Route path="/" element={<ChatRoute />} />
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
    </AuthProvider>
  )
}

export default App
