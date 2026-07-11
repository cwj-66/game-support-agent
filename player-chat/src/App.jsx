import { BrowserRouter, Routes, Route } from 'react-router-dom'
import PlayerLayout from './layout/PlayerLayout'
import ChatPage from './pages/ChatPage'
import TicketsPage from './pages/TicketsPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<PlayerLayout />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/tickets" element={<TicketsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
