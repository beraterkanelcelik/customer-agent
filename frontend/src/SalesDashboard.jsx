import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Phone, PhoneOff, PhoneIncoming, PhoneMissed, Clock, User, Mic, MicOff, ArrowLeft, Mail, X } from 'lucide-react'
import { useLiveKit } from './hooks/useLiveKit'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'

export default function SalesDashboard() {
  const [isConnected, setIsConnected] = useState(false)
  const [incomingCall, setIncomingCall] = useState(null)
  const [callHistory, setCallHistory] = useState([])
  const [activeCall, setActiveCall] = useState(null)
  const [isMuted, setIsMuted] = useState(false)
  const [salesId, setSalesId] = useState('sales_001')
  const [ringTimeout, setRingTimeout] = useState(null)
  const [emails, setEmails] = useState([])
  const [selectedEmail, setSelectedEmail] = useState(null)
  const wsRef = useRef(null)
  const audioRef = useRef(null)

  // LiveKit for voice when call is accepted
  const { connect, disconnect, toggleMute, isConnected: isLiveKitConnected } = useLiveKit()

  // Connect to sales WebSocket
  useEffect(() => {
    const connectWs = () => {
      const ws = new WebSocket(`${WS_URL}/ws/sales`)

      ws.onopen = () => {
        setIsConnected(true)
        console.log('Sales WebSocket connected')
      }

      ws.onclose = () => {
        setIsConnected(false)
        console.log('Sales WebSocket disconnected')
        // Reconnect after 3 seconds
        setTimeout(connectWs, 3000)
      }

      ws.onerror = (err) => {
        console.error('Sales WebSocket error:', err)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          handleMessage(data)
        } catch (e) {
          console.error('Failed to parse message:', e)
        }
      }

      wsRef.current = ws
    }

    connectWs()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [])

  const handleMessage = useCallback((data) => {
    console.log('Sales received:', data)

    switch (data.type) {
      case 'incoming_call':
        // Play ring sound
        playRingSound()
        setIncomingCall({
          sessionId: data.session_id,
          customerName: data.customer_name,
          customerPhone: data.customer_phone,
          reason: data.reason,
          timestamp: new Date(data.timestamp)
        })
        break

      case 'call_timeout':
        // Call timed out
        if (incomingCall?.sessionId === data.session_id) {
          stopRingSound()
          addToHistory({
            ...incomingCall,
            status: 'missed',
            endTime: new Date()
          })
          setIncomingCall(null)
        }
        break

      case 'response_acknowledged':
        console.log('Response acknowledged:', data)
        break

      case 'email_notification':
        // Add email to the list
        setEmails(prev => [{
          id: Date.now(),
          ...data.email,
          read: false
        }, ...prev].slice(0, 20))
        break

      case 'heartbeat':
        // Respond to heartbeat
        break
    }
  }, [incomingCall])

  const playRingSound = () => {
    // Create a simple ring tone using Web Audio API
    try {
      const audioContext = new (window.AudioContext || window.webkitAudioContext)()
      const oscillator = audioContext.createOscillator()
      const gainNode = audioContext.createGain()

      oscillator.connect(gainNode)
      gainNode.connect(audioContext.destination)

      oscillator.frequency.value = 440
      oscillator.type = 'sine'
      gainNode.gain.value = 0.3

      oscillator.start()

      // Ring pattern: on-off-on-off
      const ringPattern = () => {
        gainNode.gain.value = 0.3
        setTimeout(() => { gainNode.gain.value = 0 }, 500)
        setTimeout(() => { gainNode.gain.value = 0.3 }, 1000)
        setTimeout(() => { gainNode.gain.value = 0 }, 1500)
      }

      ringPattern()
      const interval = setInterval(ringPattern, 2000)

      audioRef.current = { oscillator, gainNode, audioContext, interval }

      // Auto-stop after 30 seconds
      setTimeout(stopRingSound, 30000)
    } catch (e) {
      console.log('Could not play ring sound:', e)
    }
  }

  const stopRingSound = () => {
    if (audioRef.current) {
      try {
        clearInterval(audioRef.current.interval)
        audioRef.current.oscillator.stop()
        audioRef.current.audioContext.close()
      } catch (e) {
        // Ignore errors when stopping
      }
      audioRef.current = null
    }
  }

  const addToHistory = (call) => {
    setCallHistory(prev => [call, ...prev].slice(0, 10))
  }

  const acceptCall = async () => {
    if (!incomingCall) return

    stopRingSound()

    // Send accept via WebSocket
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'respond_to_call',
        session_id: incomingCall.sessionId,
        accepted: true,
        sales_id: salesId
      }))
    }

    // Get LiveKit token and join room
    try {
      const tokenRes = await fetch(`${API_URL}/api/sales/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: incomingCall.sessionId,
          sales_id: salesId
        })
      })
      const tokenData = await tokenRes.json()

      // Connect to LiveKit
      await connect(tokenData.livekit_url, tokenData.token)

      setActiveCall({
        ...incomingCall,
        status: 'connected',
        connectedAt: new Date()
      })
      setIncomingCall(null)

    } catch (err) {
      console.error('Failed to join call:', err)
      addToHistory({
        ...incomingCall,
        status: 'error',
        error: err.message
      })
      setIncomingCall(null)
    }
  }

  const declineCall = () => {
    if (!incomingCall) return

    stopRingSound()

    // Send decline via WebSocket
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'respond_to_call',
        session_id: incomingCall.sessionId,
        accepted: false,
        sales_id: salesId
      }))
    }

    addToHistory({
      ...incomingCall,
      status: 'declined',
      endTime: new Date()
    })
    setIncomingCall(null)
  }

  const endCall = async () => {
    if (!activeCall) return

    await disconnect()

    addToHistory({
      ...activeCall,
      status: 'completed',
      endTime: new Date()
    })
    setActiveCall(null)
    setIsMuted(false)
  }

  const handleMuteToggle = () => {
    toggleMute()
    setIsMuted(!isMuted)
  }

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              to="/"
              className="p-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
            >
              <ArrowLeft size={20} />
            </Link>
            <div className="flex items-center gap-3">
              <div className="text-3xl">{'\u{1F4DE}'}</div>
              <div>
                <h1 className="text-xl font-bold">Sales Dashboard</h1>
                <p className="text-sm text-gray-400">Springfield Auto</p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Sales ID Input */}
            <div className="flex items-center gap-2">
              <User size={16} className="text-gray-400" />
              <input
                type="text"
                value={salesId}
                onChange={(e) => setSalesId(e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-32"
                placeholder="Sales ID"
              />
            </div>

            {/* Connection Status */}
            <div className={`flex items-center gap-2 px-4 py-2 rounded-full ${
              isConnected
                ? 'bg-green-900/50 text-green-300'
                : 'bg-red-900/50 text-red-300'
            }`}>
              <div className={`w-2 h-2 rounded-full ${
                isConnected ? 'bg-green-400 animate-pulse' : 'bg-red-400'
              }`} />
              <span className="text-sm font-medium">
                {isConnected ? 'Online' : 'Offline'}
              </span>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Incoming Call Alert */}
        {incomingCall && (
          <div className="bg-green-900/30 border-2 border-green-500 rounded-xl p-6 animate-pulse">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 bg-green-500 rounded-full flex items-center justify-center animate-bounce">
                  <PhoneIncoming size={32} className="text-white" />
                </div>
                <div>
                  <h2 className="text-2xl font-bold text-green-300">Incoming Call</h2>
                  <p className="text-lg">{incomingCall.customerName}</p>
                  <p className="text-gray-400">{incomingCall.customerPhone}</p>
                  <p className="text-sm text-gray-500 mt-1">{incomingCall.reason}</p>
                </div>
              </div>

              <div className="flex gap-4">
                <button
                  onClick={declineCall}
                  className="px-6 py-3 bg-red-600 hover:bg-red-700 rounded-full flex items-center gap-2 transition-colors"
                >
                  <PhoneOff size={20} />
                  Decline
                </button>
                <button
                  onClick={acceptCall}
                  className="px-6 py-3 bg-green-600 hover:bg-green-700 rounded-full flex items-center gap-2 transition-colors"
                >
                  <Phone size={20} />
                  Accept
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Active Call */}
        {activeCall && (
          <div className="bg-blue-900/30 border border-blue-700 rounded-xl p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 bg-blue-500 rounded-full flex items-center justify-center">
                  <Phone size={32} className="text-white" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-blue-300">Active Call</h2>
                  <p className="text-lg">{activeCall.customerName}</p>
                  <p className="text-gray-400">{activeCall.customerPhone}</p>
                  <p className="text-sm text-green-400 mt-1">
                    Connected {activeCall.connectedAt?.toLocaleTimeString()}
                  </p>
                </div>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={handleMuteToggle}
                  className={`p-3 rounded-full ${
                    isMuted ? 'bg-red-600' : 'bg-gray-700 hover:bg-gray-600'
                  }`}
                >
                  {isMuted ? <MicOff size={24} /> : <Mic size={24} />}
                </button>
                <button
                  onClick={endCall}
                  className="px-6 py-3 bg-red-600 hover:bg-red-700 rounded-full flex items-center gap-2 transition-colors"
                >
                  <PhoneOff size={20} />
                  End Call
                </button>
              </div>
            </div>
          </div>
        )}

        {/* No Active Call State */}
        {!incomingCall && !activeCall && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
            <div className="w-24 h-24 bg-gray-800 rounded-full flex items-center justify-center mx-auto mb-4">
              <Phone size={48} className="text-gray-600" />
            </div>
            <h2 className="text-xl font-semibold text-gray-400">Waiting for calls</h2>
            <p className="text-gray-500 mt-2">
              Incoming escalation requests will appear here
            </p>
          </div>
        )}

        {/* Call History */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
            <Clock size={18} className="text-gray-400" />
            <h2 className="font-semibold">Recent Calls</h2>
          </div>

          <div className="divide-y divide-gray-800">
            {callHistory.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                No call history yet
              </div>
            ) : (
              callHistory.map((call, index) => (
                <div key={index} className="px-4 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                      call.status === 'completed' ? 'bg-green-900/50' :
                      call.status === 'missed' ? 'bg-yellow-900/50' :
                      call.status === 'declined' ? 'bg-red-900/50' :
                      'bg-gray-800'
                    }`}>
                      {call.status === 'completed' ? (
                        <Phone size={18} className="text-green-400" />
                      ) : call.status === 'missed' ? (
                        <PhoneMissed size={18} className="text-yellow-400" />
                      ) : (
                        <PhoneOff size={18} className="text-red-400" />
                      )}
                    </div>
                    <div>
                      <p className="font-medium">{call.customerName}</p>
                      <p className="text-sm text-gray-500">{call.customerPhone}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`text-xs px-2 py-1 rounded ${
                      call.status === 'completed' ? 'bg-green-900/50 text-green-300' :
                      call.status === 'missed' ? 'bg-yellow-900/50 text-yellow-300' :
                      'bg-red-900/50 text-red-300'
                    }`}>
                      {call.status}
                    </span>
                    <p className="text-xs text-gray-500 mt-1">
                      {call.timestamp?.toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Email Notifications */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Mail size={18} className="text-blue-400" />
              <h2 className="font-semibold">Email Notifications</h2>
              {emails.filter(e => !e.read).length > 0 && (
                <span className="bg-blue-500 text-xs px-2 py-0.5 rounded-full">
                  {emails.filter(e => !e.read).length} new
                </span>
              )}
            </div>
            <span className="text-xs text-gray-500">(Simulated - shown for demo)</span>
          </div>

          <div className="divide-y divide-gray-800 max-h-64 overflow-y-auto">
            {emails.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                No emails yet - emails appear here when calls are missed/declined
              </div>
            ) : (
              emails.map((email) => (
                <div
                  key={email.id}
                  onClick={() => {
                    setSelectedEmail(email)
                    setEmails(prev => prev.map(e =>
                      e.id === email.id ? { ...e, read: true } : e
                    ))
                  }}
                  className={`px-4 py-3 cursor-pointer hover:bg-gray-800/50 transition-colors ${
                    !email.read ? 'bg-blue-900/20' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                        !email.read ? 'bg-blue-900/50' : 'bg-gray-800'
                      }`}>
                        <Mail size={18} className={!email.read ? 'text-blue-400' : 'text-gray-500'} />
                      </div>
                      <div>
                        <p className={`font-medium ${!email.read ? 'text-blue-300' : ''}`}>
                          {email.subject}
                        </p>
                        <p className="text-sm text-gray-500">
                          Callback: {email.callback_time}
                        </p>
                      </div>
                    </div>
                    <div className="text-xs text-gray-500">
                      {new Date(email.timestamp).toLocaleTimeString()}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Instructions */}
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 text-sm text-gray-400">
          <h3 className="font-semibold text-gray-300 mb-2">How it works:</h3>
          <ol className="list-decimal list-inside space-y-1">
            <li>Keep this dashboard open in a separate tab</li>
            <li>When a customer requests human assistance, you'll see an incoming call</li>
            <li>Click "Accept" to join the voice call with the customer</li>
            <li>Click "Decline" to let the system schedule a callback</li>
            <li>If you don't respond within 30 seconds, it auto-declines</li>
            <li>Declined/missed calls generate email notifications (shown above)</li>
          </ol>
        </div>
      </main>

      {/* Email Modal */}
      {selectedEmail && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl max-w-lg w-full max-h-[80vh] overflow-hidden">
            <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Mail size={18} className="text-blue-400" />
                <span className="font-semibold">Email Preview</span>
              </div>
              <button
                onClick={() => setSelectedEmail(null)}
                className="p-1 hover:bg-gray-700 rounded"
              >
                <X size={18} />
              </button>
            </div>
            <div className="p-4 space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">To:</span>
                <span>{selectedEmail.to}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Subject:</span>
                <span className="font-medium">{selectedEmail.subject}</span>
              </div>
              <hr className="border-gray-700" />
              <pre className="text-sm whitespace-pre-wrap font-mono bg-gray-800 p-4 rounded-lg overflow-auto max-h-64">
                {selectedEmail.body}
              </pre>
            </div>
            <div className="px-4 py-3 bg-gray-800 border-t border-gray-700 flex justify-end">
              <button
                onClick={() => setSelectedEmail(null)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
