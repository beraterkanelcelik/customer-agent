import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import App from './App'
import SalesDashboard from './SalesDashboard'
import AgentFlowDiagram from './AgentFlowDiagram'
import './styles/main.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/sales" element={<SalesDashboard />} />
        <Route path="/flow" element={<AgentFlowDiagram />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)
