import React, { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Phone, PhoneOff, GitBranch, PhoneCall, PhoneIncoming, Waves } from 'lucide-react'
import Transcript from './components/Transcript'
import AgentState from './components/AgentState'
import CustomerInfo from './components/CustomerInfo'
import BookingSlots from './components/BookingSlots'
import AvailabilityCalendar from './components/AvailabilityCalendar'
import { useWebSocket } from './hooks/useWebSocket'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [isCallActive, setIsCallActive] = useState(false)
  const [callState, setCallState] = useState('idle') // idle, connecting, ai_conversation, processing, escalating, in_conference, ended
  const [customerPhone, setCustomerPhone] = useState(null)
  const [transcript, setTranscript] = useState([])
  const [agentState, setAgentState] = useState({
    currentAgent: 'unified',
    intent: null,
    confidence: 0,
    escalationInProgress: false,
    humanAgentStatus: null
  })
  const [customer, setCustomer] = useState(null)
  const [bookingSlots, setBookingSlots] = useState({})
  const [confirmedAppointment, setConfirmedAppointment] = useState(null)
  const [bookingInProgress, setBookingInProgress] = useState(false)
  const [error, setError] = useState(null)
  const [latency, setLatency] = useState(null)
  const [notifications, setNotifications] = useState([])
  const [voiceStatus, setVoiceStatus] = useState({ ready: false, stt_loaded: false, tts_loaded: false })
  const [twilioPhone, setTwilioPhone] = useState(null)

  // WebSocket for state updates - always connect to dashboard endpoint
  // The dashboard endpoint receives ALL events (both session-specific and global)
  // via dashboard_callback, so there's no need to switch URLs when a call starts
  const { sendMessage, isConnected: wsConnected } = useWebSocket(
    `${WS_URL}/ws/dashboard`,
    {
      onMessage: (data) => {
        handleWSMessage(data)
      },
      onError: (err) => {
        console.error('WebSocket error:', err)
      }
    }
  )

  // Poll voice/backend status
  useEffect(() => {
    const checkStatus = async () => {
      try {
        // Check voice models status
        const voiceRes = await fetch(`${API_URL}/api/voice/status`)
        const voiceData = await voiceRes.json()
        setVoiceStatus(voiceData)

        // Get Twilio phone number from health endpoint or config
        const healthRes = await fetch(`${API_URL}/health`)
        const healthData = await healthRes.json()
        if (healthData.twilio_phone) {
          setTwilioPhone(healthData.twilio_phone)
        }
      } catch (err) {
        console.error('Failed to check status:', err)
      }
    }

    checkStatus()
    const interval = setInterval(() => {
      if (!voiceStatus.ready) {
        checkStatus()
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [voiceStatus.ready])

  const handleWSMessage = useCallback((data) => {
    switch (data.type) {
      // Twilio call events
      case 'call_started':
        setSessionId(data.session_id)
        setIsCallActive(true)
        setCallState('connecting')
        setCustomerPhone(data.customer_phone)
        setTranscript([])
        setBookingSlots({})
        setConfirmedAppointment(null)
        setBookingInProgress(false)
        setCustomer(null)
        setAgentState({
          currentAgent: 'unified',
          intent: null,
          confidence: 0,
          escalationInProgress: false,
          humanAgentStatus: null
        })
        break

      case 'stream_started':
      case 'stream_resumed':
        setCallState('ai_conversation')
        if (data.resumed) {
          // Returned from escalation
          setAgentState(prev => ({
            ...prev,
            escalationInProgress: false,
            humanAgentStatus: null
          }))
        }
        break

      case 'returned_to_ai':
        // Customer returned to AI after escalation failed
        setCallState('ai_conversation')
        setAgentState(prev => ({
          ...prev,
          escalationInProgress: false,
          humanAgentStatus: 'returned_to_ai'
        }))
        break

      case 'stream_ended':
      case 'call_ended':
        setIsCallActive(false)
        setCallState('idle')
        // Clear escalation state but keep transcript and other state for review
        setAgentState(prev => ({
          ...prev,
          escalationInProgress: false,
          humanAgentStatus: null
        }))
        break

      case 'call_ending':
        setCallState('ended')
        // Agent is saying goodbye
        break

      case 'human_connected':
        setCallState('in_conference')
        setAgentState(prev => ({
          ...prev,
          humanAgentStatus: 'connected'
        }))
        break

      case 'human_unavailable':
        // Human is unavailable - will be returned to AI
        setAgentState(prev => ({
          ...prev,
          humanAgentStatus: 'unavailable'
        }))
        // Note: The returned_to_ai event will follow shortly
        break

      case 'escalation':
        setCallState('escalating')
        setAgentState(prev => ({
          ...prev,
          escalationInProgress: true,
          humanAgentStatus: data.status || 'checking'
        }))
        break

      case 'human_status':
        // Twilio call status updates (initiated, ringing, waiting_confirmation, confirmed, no-answer, canceled, etc.)
        const isTerminalStatus = ['no-answer', 'busy', 'failed', 'canceled', 'returned_to_ai', 'declined', 'voicemail'].includes(data.status)
        const isInProgressStatus = ['initiated', 'calling', 'ringing', 'waiting_confirmation', 'confirmed'].includes(data.status)
        setAgentState(prev => ({
          ...prev,
          // Only keep escalation in progress for active statuses
          escalationInProgress: isInProgressStatus || data.status === 'connected',
          humanAgentStatus: data.status || prev.humanAgentStatus
        }))
        // Clear terminal status after 10 seconds so the panel goes away
        if (isTerminalStatus) {
          setTimeout(() => {
            setAgentState(prev => {
              // Only clear if still showing the same terminal status
              if (['no-answer', 'busy', 'failed', 'canceled', 'returned_to_ai', 'declined', 'voicemail'].includes(prev.humanAgentStatus)) {
                return { ...prev, humanAgentStatus: null }
              }
              return prev
            })
          }, 10000)
        }
        break

      // Standard state events
      case 'state_update':
        setAgentState(prev => {
          const escalationInProgress = data.escalation_in_progress ?? prev.escalationInProgress
          // Clear human status if escalation is not in progress and status is null/none
          let humanStatus = data.human_agent_status ?? prev.humanAgentStatus
          if (!escalationInProgress && (data.human_agent_status === null || data.human_agent_status === 'none')) {
            humanStatus = null
          }
          return {
            ...prev,
            currentAgent: data.current_agent ?? prev.currentAgent,
            intent: data.intent ?? prev.intent,
            confidence: data.confidence ?? prev.confidence,
            escalationInProgress,
            humanAgentStatus: humanStatus
          }
        })
        if (data.customer) setCustomer(data.customer)
        if (data.booking_slots) {
          setBookingSlots(data.booking_slots)
          const hasAnySlot = Object.values(data.booking_slots).some(v => v !== null && v !== undefined)
          if (hasAnySlot) {
            setBookingInProgress(true)
          }
        }
        if (data.confirmed_appointment) {
          setConfirmedAppointment(data.confirmed_appointment)
          setBookingInProgress(false)
        }
        if (data.intent === 'book_service' || data.intent === 'book_test_drive') {
          setBookingInProgress(true)
        }
        break

      case 'transcript':
        setTranscript(prev => [...prev, {
          role: data.role,
          content: data.content,
          timestamp: new Date().toLocaleTimeString(),
          agentType: data.agent_type
        }])
        // Mark as processing when user speaks, ai_conversation when agent responds
        if (data.role === 'user') {
          setCallState('processing')
        } else {
          setCallState('ai_conversation')
        }
        break

      case 'notification':
        const newNotification = {
          id: data.notification_id,
          message: data.message,
          priority: data.priority,
          timestamp: new Date().toLocaleTimeString()
        }
        setNotifications(prev => [...prev, newNotification])
        setTranscript(prev => [...prev, {
          role: 'assistant',
          content: data.message,
          timestamp: new Date().toLocaleTimeString(),
          agentType: 'escalation',
          isNotification: true
        }])
        setTimeout(() => {
          setNotifications(prev => prev.filter(n => n.id !== data.notification_id))
        }, 10000)
        break

      case 'latency':
        const latencyData = {
          stt_ms: data.stt_ms,
          llm_ms: data.llm_ms,
          tts_ms: data.tts_ms,
          total_ms: data.total_ms
        }
        setLatency(latencyData)
        setTranscript(prev => {
          const updated = [...prev]
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === 'assistant' && !updated[i].latency) {
              updated[i] = { ...updated[i], latency: latencyData }
              break
            }
          }
          return updated
        })
        break

      case 'availability_update':
        setAvailabilityWsUpdate({
          type: data.type,
          slot_date: data.slot_date,
          slot_time: data.slot_time,
          appointment_type: data.appointment_type,
          inventory_id: data.inventory_id,
          is_available: data.is_available,
          timestamp: Date.now()
        })
        break

      case 'booking_slot_update':
        setBookingSlots(prev => ({
          ...prev,
          [data.slot_name]: data.slot_value,
          ...data.all_slots
        }))
        setBookingInProgress(true)
        break
    }
  }, [])

  const [availabilityWsUpdate, setAvailabilityWsUpdate] = useState(null)

  const getCallStateDisplay = () => {
    switch (callState) {
      case 'connecting': return { text: 'Connecting...', color: 'text-warning-600', bg: 'bg-warning-50', border: 'border-warning-200' }
      case 'ai_conversation': return { text: 'AI Speaking', color: 'text-success-600', bg: 'bg-success-50', border: 'border-success-200' }
      case 'processing': return { text: 'Processing...', color: 'text-soft-600', bg: 'bg-soft-50', border: 'border-soft-200' }
      case 'escalating': return { text: 'Escalating', color: 'text-warning-600', bg: 'bg-warning-50', border: 'border-warning-200' }
      case 'in_conference': return { text: 'Human Connected', color: 'text-accent-600', bg: 'bg-accent-50', border: 'border-accent-200' }
      case 'ended': return { text: 'Ending...', color: 'text-slate-500', bg: 'bg-slate-50', border: 'border-slate-200' }
      default: return { text: 'Ready', color: 'text-slate-500', bg: 'bg-white/60', border: 'border-surface-300' }
    }
  }

  const callStateDisplay = getCallStateDisplay()

  return (
    <div className="min-h-screen relative">
      {/* Header */}
      <header className="glass-card-solid sticky top-0 z-40 border-b border-surface-300/50">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            {/* Logo Section */}
            <div className="flex items-center gap-4 animate-fade-in">
              <div className="relative">
                <div className="w-12 h-12 bg-gradient-to-br from-accent-400 to-soft-500 rounded-2xl flex items-center justify-center shadow-soft">
                  <span className="text-2xl">🚗</span>
                </div>
                <div className="absolute -bottom-1 -right-1 w-4 h-4 bg-success-400 rounded-full border-2 border-white shadow-sm" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-800 font-display">
                  Springfield Auto
                </h1>
                <p className="text-sm text-slate-500">Voice Agent Dashboard</p>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-4">
              {/* Agent Flow Link */}
              <Link
                to="/flow"
                className="flex items-center gap-2 px-4 py-2.5 bg-white/60 hover:bg-white border border-surface-300 hover:border-accent-300 rounded-xl text-sm text-slate-600 hover:text-accent-600 transition-all duration-200 shadow-sm hover:shadow"
              >
                <GitBranch size={16} />
                <span className="font-medium">Agent Flow</span>
              </Link>

              {/* Latency Display */}
              {isCallActive && latency && (
                <div className="flex items-center gap-4 px-5 py-2.5 rounded-xl bg-white/80 border border-surface-300 shadow-sm animate-fade-in">
                  <div className="flex flex-col items-center">
                    <span className="text-[10px] text-slate-400 uppercase tracking-wide">STT</span>
                    <span className="text-soft-600 font-mono text-sm font-medium">{latency.stt_ms}ms</span>
                  </div>
                  <div className="flex flex-col items-center">
                    <span className="text-[10px] text-slate-400 uppercase tracking-wide">LLM</span>
                    <span className="text-accent-600 font-mono text-sm font-medium">{latency.llm_ms}ms</span>
                  </div>
                  <div className="flex flex-col items-center">
                    <span className="text-[10px] text-slate-400 uppercase tracking-wide">TTS</span>
                    <span className="text-success-600 font-mono text-sm font-medium">{latency.tts_ms}ms</span>
                  </div>
                  <div className="flex flex-col items-center pl-3 border-l border-surface-300">
                    <span className="text-[10px] text-slate-400 uppercase tracking-wide">Total</span>
                    <span className={`font-mono text-sm font-bold ${
                      latency.total_ms < 3000 ? 'text-success-600' :
                      latency.total_ms < 6000 ? 'text-warning-600' : 'text-error-600'
                    }`}>{(latency.total_ms / 1000).toFixed(1)}s</span>
                  </div>
                </div>
              )}

              {/* Voice Models Status */}
              {!isCallActive && (
                <div className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm border transition-all duration-300 ${
                  voiceStatus.ready
                    ? 'bg-success-50 border-success-200 text-success-700'
                    : 'bg-warning-50 border-warning-200 text-warning-700'
                }`}>
                  {voiceStatus.ready ? (
                    <>
                      <div className="w-2 h-2 rounded-full bg-success-500 status-dot status-dot-success" />
                      <span className="font-medium">Models Ready</span>
                    </>
                  ) : (
                    <>
                      <div className="w-2 h-2 rounded-full bg-warning-500 animate-pulse" />
                      <span className="font-medium">
                        Loading {!voiceStatus.stt_loaded ? 'STT' : 'TTS'}...
                      </span>
                    </>
                  )}
                </div>
              )}

              {/* Call Status Badge */}
              <div className={`flex items-center gap-2.5 px-5 py-2.5 rounded-full border transition-all duration-300 ${callStateDisplay.bg} ${callStateDisplay.color} ${callStateDisplay.border}`}>
                {isCallActive ? (
                  <>
                    <PhoneCall size={16} className="animate-pulse" />
                    <span className="text-sm font-semibold">{callStateDisplay.text}</span>
                  </>
                ) : (
                  <>
                    <Phone size={16} />
                    <span className="text-sm font-medium">Waiting for Call</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Call Instructions Banner */}
      {!isCallActive && (
        <div className="bg-gradient-to-r from-accent-50 via-soft-50 to-accent-50 border-b border-accent-100 animate-fade-in">
          <div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
            <div className="flex items-center gap-5">
              <div className="w-14 h-14 bg-gradient-to-br from-accent-400 to-soft-500 rounded-2xl flex items-center justify-center shadow-soft float-animation">
                <PhoneIncoming size={24} className="text-white" />
              </div>
              <div>
                <p className="text-accent-800 font-semibold text-lg">
                  Call the AI Agent via Phone
                </p>
                <p className="text-accent-600/70 text-sm mt-0.5">
                  Dashboard will automatically display the conversation when a call is received
                </p>
              </div>
            </div>
            {twilioPhone && (
              <div className="flex items-center gap-3 px-5 py-3 bg-white/80 backdrop-blur-sm rounded-2xl border border-accent-200 shadow-soft">
                <Phone size={18} className="text-accent-500" />
                <span className="text-accent-800 font-mono text-xl font-semibold tracking-wide">{twilioPhone}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Active Call Banner */}
      {isCallActive && customerPhone && (
        <div className="bg-gradient-to-r from-success-50 via-success-50/50 to-success-50 border-b border-success-200 animate-fade-in">
          <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-5">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-success-500 status-dot status-dot-success" />
              <Waves size={20} className="text-success-500 animate-pulse" />
            </div>
            <span className="text-success-800 font-medium">
              Active call from <span className="font-mono font-semibold bg-success-100 px-2 py-0.5 rounded-md">{customerPhone}</span>
            </span>
            <span className="text-success-600/60 text-sm">
              Session: {sessionId}
            </span>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="bg-error-50 border-b border-error-200 px-6 py-4 animate-fade-in">
          <div className="max-w-7xl mx-auto text-error-700 text-sm font-medium">
            {error}
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-7xl mx-auto p-6 relative z-10">
        <div className="grid grid-cols-12 gap-6">

          {/* Left: Transcript */}
          <div className="col-span-5 animate-fade-in-up" style={{ animationDelay: '0.1s' }}>
            <Transcript messages={transcript} isActive={isCallActive} />
          </div>

          {/* Middle: Agent State & Booking */}
          <div className="col-span-4 space-y-6">
            <div className="animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
              <AgentState state={agentState} />
            </div>
            <div className="animate-fade-in-up" style={{ animationDelay: '0.3s' }}>
              <BookingSlots slots={bookingSlots} confirmedAppointment={confirmedAppointment} intent={agentState.intent} bookingInProgress={bookingInProgress} />
            </div>
          </div>

          {/* Right: Customer & Availability */}
          <div className="col-span-3 space-y-6">
            <div className="animate-fade-in-up" style={{ animationDelay: '0.4s' }}>
              <CustomerInfo customer={customer} />
            </div>
            <div className="animate-fade-in-up" style={{ animationDelay: '0.5s' }}>
              <AvailabilityCalendar
                appointmentType={bookingSlots?.appointment_type}
                wsUpdate={availabilityWsUpdate}
              />
            </div>
          </div>

        </div>
      </main>

      {/* Session ID Footer */}
      {sessionId && (
        <footer className="fixed bottom-0 left-0 right-0 glass-card-solid border-t border-surface-300/50 px-6 py-3 z-40">
          <div className="max-w-7xl mx-auto flex items-center justify-between text-xs">
            <span className="text-slate-500 font-mono">Session: {sessionId}</span>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-success-500' : 'bg-error-500'}`} />
              <span className={wsConnected ? 'text-success-600' : 'text-error-600'}>
                WebSocket {wsConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
          </div>
        </footer>
      )}

      {/* Notification Toasts */}
      <div className="fixed top-24 right-6 space-y-3 z-50">
        {notifications.map((notif, index) => (
          <div
            key={notif.id}
            className={`max-w-sm p-4 rounded-2xl shadow-glass-lg border backdrop-blur-md animate-slide-in-right ${
              notif.priority === 'interrupt'
                ? 'bg-success-50/95 border-success-200 text-success-800'
                : 'bg-warning-50/95 border-warning-200 text-warning-800'
            }`}
            style={{ animationDelay: `${index * 0.1}s` }}
          >
            <div className="flex items-start gap-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                notif.priority === 'interrupt'
                  ? 'bg-success-100'
                  : 'bg-warning-100'
              }`}>
                <span className="text-xl">
                  {notif.priority === 'interrupt' ? '✓' : '⏱'}
                </span>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium">{notif.message}</p>
                <p className="text-xs opacity-60 mt-1">{notif.timestamp}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
