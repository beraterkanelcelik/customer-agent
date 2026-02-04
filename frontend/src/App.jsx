import React, { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Phone, PhoneOff, GitBranch, PhoneCall, PhoneIncoming } from 'lucide-react'
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
      case 'connecting': return { text: 'Connecting...', color: 'text-yellow-400', bg: 'bg-yellow-900/50' }
      case 'ai_conversation': return { text: 'AI Speaking', color: 'text-green-400', bg: 'bg-green-900/50' }
      case 'processing': return { text: 'Processing...', color: 'text-blue-400', bg: 'bg-blue-900/50' }
      case 'escalating': return { text: 'Escalating', color: 'text-orange-400', bg: 'bg-orange-900/50' }
      case 'in_conference': return { text: 'Human Connected', color: 'text-purple-400', bg: 'bg-purple-900/50' }
      case 'ended': return { text: 'Ending...', color: 'text-gray-400', bg: 'bg-gray-700/50' }
      default: return { text: 'Ready', color: 'text-gray-400', bg: 'bg-gray-800' }
    }
  }

  const callStateDisplay = getCallStateDisplay()

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950">
      {/* Header */}
      <header className="bg-gray-900/80 backdrop-blur-lg border-b border-gray-800/50 px-6 py-4 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center text-xl shadow-lg shadow-indigo-500/20">
              🚗
            </div>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-white to-gray-300 bg-clip-text text-transparent">
                Springfield Auto
              </h1>
              <p className="text-sm text-gray-400">Voice Agent Dashboard</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Agent Flow Diagram Link */}
            <Link
              to="/flow"
              className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition-colors"
            >
              <GitBranch size={16} />
              <span>Agent Flow</span>
            </Link>

            {/* Latency Display */}
            {isCallActive && latency && (
              <div className="flex items-center gap-3 px-4 py-2 rounded-lg bg-gray-800 text-xs">
                <div className="flex flex-col items-center">
                  <span className="text-gray-400">STT</span>
                  <span className="text-blue-400 font-mono">{latency.stt_ms}ms</span>
                </div>
                <div className="flex flex-col items-center">
                  <span className="text-gray-400">LLM</span>
                  <span className="text-purple-400 font-mono">{latency.llm_ms}ms</span>
                </div>
                <div className="flex flex-col items-center">
                  <span className="text-gray-400">TTS</span>
                  <span className="text-green-400 font-mono">{latency.tts_ms}ms</span>
                </div>
                <div className="flex flex-col items-center border-l border-gray-700 pl-3">
                  <span className="text-gray-400">Total</span>
                  <span className={`font-mono font-bold ${
                    latency.total_ms < 3000 ? 'text-green-400' :
                    latency.total_ms < 6000 ? 'text-yellow-400' : 'text-red-400'
                  }`}>{(latency.total_ms / 1000).toFixed(1)}s</span>
                </div>
              </div>
            )}

            {/* Voice Models Status */}
            {!isCallActive && (
              <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs ${
                voiceStatus.ready
                  ? 'bg-green-900/30 text-green-400'
                  : 'bg-yellow-900/30 text-yellow-400'
              }`}>
                {voiceStatus.ready ? (
                  <>
                    <div className="w-2 h-2 rounded-full bg-green-400" />
                    <span>Models Ready</span>
                  </>
                ) : (
                  <>
                    <div className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
                    <span>
                      Loading {!voiceStatus.stt_loaded ? 'STT' : 'TTS'}...
                    </span>
                  </>
                )}
              </div>
            )}

            {/* Call Status */}
            <div className={`flex items-center gap-2 px-4 py-2 rounded-full ${callStateDisplay.bg} ${callStateDisplay.color}`}>
              {isCallActive ? (
                <>
                  <PhoneCall size={16} className="animate-pulse" />
                  <span className="text-sm font-medium">{callStateDisplay.text}</span>
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
      </header>

      {/* Call Instructions Banner */}
      {!isCallActive && (
        <div className="bg-indigo-900/30 border-b border-indigo-800/50 px-6 py-4">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-4">
              <PhoneIncoming size={24} className="text-indigo-400" />
              <div>
                <p className="text-indigo-200 font-medium">
                  Call the AI Agent via Phone
                </p>
                <p className="text-indigo-300/70 text-sm">
                  Dashboard will automatically display the conversation when a call is received
                </p>
              </div>
            </div>
            {twilioPhone && (
              <div className="flex items-center gap-2 px-4 py-2 bg-indigo-800/50 rounded-lg">
                <Phone size={16} className="text-indigo-300" />
                <span className="text-indigo-100 font-mono text-lg">{twilioPhone}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Active Call Banner */}
      {isCallActive && customerPhone && (
        <div className="bg-green-900/30 border-b border-green-800/50 px-6 py-3">
          <div className="max-w-7xl mx-auto flex items-center gap-4">
            <div className="w-3 h-3 rounded-full bg-green-400 animate-pulse" />
            <span className="text-green-200">
              Active call from <span className="font-mono font-medium">{customerPhone}</span>
            </span>
            <span className="text-green-400/70 text-sm">
              Session: {sessionId}
            </span>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="bg-red-900/50 border-b border-red-800 px-6 py-3">
          <div className="max-w-7xl mx-auto text-red-300 text-sm">
            {error}
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-7xl mx-auto p-6">
        <div className="grid grid-cols-12 gap-6">

          {/* Left: Transcript */}
          <div className="col-span-5">
            <Transcript messages={transcript} isActive={isCallActive} />
          </div>

          {/* Middle: Agent State & Booking */}
          <div className="col-span-4 space-y-6">
            <AgentState state={agentState} />
            <BookingSlots slots={bookingSlots} confirmedAppointment={confirmedAppointment} intent={agentState.intent} bookingInProgress={bookingInProgress} />
          </div>

          {/* Right: Customer & Availability */}
          <div className="col-span-3 space-y-6">
            <CustomerInfo customer={customer} />
            <AvailabilityCalendar
              appointmentType={bookingSlots?.appointment_type}
              wsUpdate={availabilityWsUpdate}
            />
          </div>

        </div>
      </main>

      {/* Session ID Footer */}
      {sessionId && (
        <footer className="fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-800 px-6 py-2">
          <div className="max-w-7xl mx-auto flex items-center justify-between text-xs text-gray-500">
            <span>Session: {sessionId}</span>
            <span>WebSocket: {wsConnected ? '🟢 Connected' : '🔴 Disconnected'}</span>
          </div>
        </footer>
      )}

      {/* Notification Toasts */}
      <div className="fixed top-20 right-6 space-y-2 z-50">
        {notifications.map((notif) => (
          <div
            key={notif.id}
            className={`max-w-sm p-4 rounded-lg shadow-lg border animate-pulse ${
              notif.priority === 'interrupt'
                ? 'bg-green-900/90 border-green-600 text-green-100'
                : 'bg-yellow-900/90 border-yellow-600 text-yellow-100'
            }`}
          >
            <div className="flex items-start gap-3">
              <div className="text-2xl">
                {notif.priority === 'interrupt' ? '✅' : '⏰'}
              </div>
              <div>
                <p className="text-sm font-medium">{notif.message}</p>
                <p className="text-xs opacity-70 mt-1">{notif.timestamp}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
