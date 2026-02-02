import React, { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Phone, PhoneOff, Mic, MicOff, Users, GitBranch } from 'lucide-react'
import CallButton from './components/CallButton'
import Transcript from './components/Transcript'
import AgentState from './components/AgentState'
import CustomerInfo from './components/CustomerInfo'
import TaskMonitor from './components/TaskMonitor'
import BookingSlots from './components/BookingSlots'
import AvailabilityCalendar from './components/AvailabilityCalendar'
import { useWebSocket } from './hooks/useWebSocket'
import { useLiveKit } from './hooks/useLiveKit'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'
const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || 'ws://localhost:7880'

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [isCallActive, setIsCallActive] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
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
  const [bookingInProgress, setBookingInProgress] = useState(false) // Tracks if booking has started
  const [pendingTasks, setPendingTasks] = useState([])
  const [error, setError] = useState(null)
  const [latency, setLatency] = useState(null)
  const [notifications, setNotifications] = useState([])
  const [voiceStatus, setVoiceStatus] = useState({ ready: false, stt_loaded: false, tts_loaded: false })

  // WebSocket for state updates
  const { sendMessage } = useWebSocket(
    sessionId ? `${WS_URL}/ws/${sessionId}` : null,
    {
      onMessage: (data) => {
        handleWSMessage(data)
      },
      onError: (err) => {
        console.error('WebSocket error:', err)
      }
    }
  )

  // LiveKit for voice
  const { connect, disconnect, toggleMute, isConnected } = useLiveKit()

  // Poll voice worker status
  useEffect(() => {
    const checkVoiceStatus = async () => {
      try {
        const res = await fetch(`${API_URL}/api/voice/status`)
        const data = await res.json()
        setVoiceStatus(data)
      } catch (err) {
        console.error('Failed to check voice status:', err)
      }
    }

    // Check immediately
    checkVoiceStatus()

    // Poll every 2 seconds until ready
    const interval = setInterval(() => {
      if (!voiceStatus.ready) {
        checkVoiceStatus()
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [voiceStatus.ready])

  const handleWSMessage = useCallback((data) => {
    switch (data.type) {
      case 'state_update':
        // Merge with existing state to support partial updates
        setAgentState(prev => ({
          ...prev,
          currentAgent: data.current_agent ?? prev.currentAgent,
          intent: data.intent ?? prev.intent,
          confidence: data.confidence ?? prev.confidence,
          escalationInProgress: data.escalation_in_progress ?? prev.escalationInProgress,
          humanAgentStatus: data.human_agent_status ?? prev.humanAgentStatus
        }))
        if (data.customer) setCustomer(data.customer)
        if (data.booking_slots) {
          setBookingSlots(data.booking_slots)
          // Start booking mode if any slot is filled
          const hasAnySlot = Object.values(data.booking_slots).some(v => v !== null && v !== undefined)
          if (hasAnySlot) {
            setBookingInProgress(true)
          }
        }
        if (data.confirmed_appointment) {
          setConfirmedAppointment(data.confirmed_appointment)
          // Reset booking mode after confirmation
          setBookingInProgress(false)
        }
        if (data.pending_tasks) setPendingTasks(data.pending_tasks)
        // Also check intent to start booking mode
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
        break

      case 'task_update':
        setPendingTasks(prev => {
          const updated = prev.filter(t => t.task_id !== data.task.task_id)
          return [...updated, data.task]
        })
        break

      case 'notification':
        // Add notification to list
        const newNotification = {
          id: data.notification_id,
          message: data.message,
          priority: data.priority,
          timestamp: new Date().toLocaleTimeString()
        }
        setNotifications(prev => [...prev, newNotification])

        // Also add to transcript so user sees it
        setTranscript(prev => [...prev, {
          role: 'assistant',
          content: data.message,
          timestamp: new Date().toLocaleTimeString(),
          agentType: 'escalation',
          isNotification: true
        }])

        // Auto-dismiss notification after 10 seconds
        setTimeout(() => {
          setNotifications(prev => prev.filter(n => n.id !== data.notification_id))
        }, 10000)
        break

      case 'latency':
        setLatency(data.data)
        // Also attach latency to the most recent assistant message
        setTranscript(prev => {
          const updated = [...prev]
          // Find the most recent assistant message without latency
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === 'assistant' && !updated[i].latency) {
              updated[i] = { ...updated[i], latency: data.data }
              break
            }
          }
          return updated
        })
        break

      case 'end_call':
        // Add farewell to transcript
        setTranscript(prev => [...prev, {
          role: 'assistant',
          content: data.farewell_message || 'Thank you for calling. Goodbye!',
          timestamp: new Date().toLocaleTimeString(),
          isSystemMessage: true
        }])
        // End call after 10 seconds to let agent fully speak the goodbye message
        setTimeout(async () => {
          try {
            await disconnect()
            setIsCallActive(false)
            // Reset booking states
            setBookingInProgress(false)
            setBookingSlots({})
            setConfirmedAppointment(null)
            setCustomer(null)
            if (sessionId) {
              await fetch(`${API_URL}/api/sessions/${sessionId}`, { method: 'DELETE' })
              setSessionId(null)
            }
          } catch (err) {
            console.error('Error ending call:', err)
          }
        }, 10000)
        break

      case 'availability_update':
        // Pass the update to AvailabilityCalendar for real-time slot update
        setAvailabilityWsUpdate({
          type: data.type,
          slot_date: data.slot_date,
          slot_time: data.slot_time,
          appointment_type: data.appointment_type,
          inventory_id: data.inventory_id,
          is_available: data.is_available,
          timestamp: Date.now() // Ensure uniqueness for useEffect trigger
        })
        break

      case 'booking_slot_update':
        // Real-time update as slots are collected (before turn ends)
        setBookingSlots(prev => ({
          ...prev,
          [data.slot_name]: data.slot_value,
          ...data.all_slots
        }))
        setBookingInProgress(true)
        break
    }
  }, [disconnect, sessionId])

  // Key to force AvailabilityCalendar refresh
  const [availabilityKey, setAvailabilityKey] = useState(0)
  // WebSocket update to pass to AvailabilityCalendar
  const [availabilityWsUpdate, setAvailabilityWsUpdate] = useState(null)

  const startCall = async () => {
    try {
      setError(null)

      // Create session
      const sessionRes = await fetch(`${API_URL}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      const sessionData = await sessionRes.json()
      setSessionId(sessionData.session_id)

      // Get LiveKit token
      const tokenRes = await fetch(`${API_URL}/api/voice/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionData.session_id })
      })
      const tokenData = await tokenRes.json()

      // Connect to LiveKit
      await connect(tokenData.livekit_url, tokenData.token)

      setIsCallActive(true)
      setTranscript([])
      setLatency(null)

    } catch (err) {
      console.error('Failed to start call:', err)
      setError('Failed to start call. Please try again.')
    }
  }

  const endCall = async () => {
    try {
      await disconnect()

      if (sessionId) {
        await fetch(`${API_URL}/api/sessions/${sessionId}`, {
          method: 'DELETE'
        })
      }

      setIsCallActive(false)
      setSessionId(null)

    } catch (err) {
      console.error('Failed to end call:', err)
    }
  }

  const handleMuteToggle = () => {
    toggleMute()
    setIsMuted(!isMuted)
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950">
      {/* Header */}
      <header className="bg-gray-900/80 backdrop-blur-lg border-b border-gray-800/50 px-6 py-4 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center text-xl shadow-lg shadow-indigo-500/20">
              {'\u{1F697}'}
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

            {/* Sales Dashboard Link */}
            <Link
              to="/sales"
              className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition-colors"
            >
              <Users size={16} />
              <span>Sales Dashboard</span>
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

            {/* Voice Worker Status */}
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
            <div className={`flex items-center gap-2 px-4 py-2 rounded-full ${
              isCallActive
                ? 'bg-green-900/50 text-green-300'
                : 'bg-gray-800 text-gray-400'
            }`}>
              <div className={`w-2 h-2 rounded-full ${
                isCallActive ? 'bg-green-400 animate-pulse' : 'bg-gray-600'
              }`} />
              <span className="text-sm font-medium">
                {isCallActive ? 'Call Active' : 'Ready'}
              </span>
            </div>

            {/* Mute Button */}
            {isCallActive && (
              <button
                onClick={handleMuteToggle}
                className={`p-2 rounded-lg ${
                  isMuted ? 'bg-red-600' : 'bg-gray-700 hover:bg-gray-600'
                }`}
              >
                {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
              </button>
            )}

            {/* Call Button */}
            <CallButton
              isActive={isCallActive}
              onStart={startCall}
              onEnd={endCall}
              disabled={!voiceStatus.ready}
            />
          </div>
        </div>
      </header>

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

          {/* Right: Customer, Tasks & Availability */}
          <div className="col-span-3 space-y-6">
            <TaskMonitor tasks={pendingTasks} />
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
          <div className="max-w-7xl mx-auto text-xs text-gray-500">
            Session: {sessionId}
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
