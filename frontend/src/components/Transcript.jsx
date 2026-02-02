import React, { useRef, useEffect, useState } from 'react'
import { MessageCircle, Clock, ChevronDown, ChevronUp } from 'lucide-react'

// Message bubble with collapsible latency details
function MessageBubble({ msg, index }) {
  const [expanded, setExpanded] = useState(false)
  const hasLatency = msg.latency && msg.role === 'assistant'

  return (
    <div
      className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
    >
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 ${
        msg.role === 'user' ? 'bg-blue-600' : 'bg-indigo-600'
      }`}>
        {msg.role === 'user' ? '\u{1F464}' : '\u{1F916}'}
      </div>

      {/* Message */}
      <div className={`flex-1 ${msg.role === 'user' ? 'text-right' : ''}`}>
        <div className={`inline-block px-4 py-2 rounded-2xl max-w-[85%] ${
          msg.role === 'user'
            ? 'bg-blue-600 rounded-br-md'
            : msg.isSystemMessage
              ? 'bg-gray-700 border border-gray-600 rounded-bl-md'
              : 'bg-gray-800 rounded-bl-md'
        }`}>
          <p className="text-sm">{msg.content}</p>
        </div>

        {/* Timestamp and agent type */}
        <div className="text-xs text-gray-500 mt-1 flex items-center gap-2 justify-start">
          <span>{msg.timestamp}</span>
          {msg.agentType && msg.role !== 'user' && (
            <span className="text-indigo-400">{'\u2022'} {msg.agentType}</span>
          )}

          {/* Latency toggle button */}
          {hasLatency && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-gray-400 hover:text-gray-300 transition-colors"
            >
              <Clock size={12} />
              <span>{(msg.latency.total_ms / 1000).toFixed(1)}s</span>
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          )}
        </div>

        {/* Expanded latency details */}
        {hasLatency && expanded && (
          <div className="mt-2 p-2 bg-gray-800/50 rounded-lg text-xs max-w-[85%] inline-block">
            <div className="grid grid-cols-4 gap-2 text-center">
              <div>
                <div className="text-gray-400 mb-1">STT</div>
                <div className="text-blue-400 font-mono">{msg.latency.stt_ms}ms</div>
              </div>
              <div>
                <div className="text-gray-400 mb-1">LLM</div>
                <div className="text-purple-400 font-mono">{msg.latency.llm_ms}ms</div>
              </div>
              <div>
                <div className="text-gray-400 mb-1">TTS</div>
                <div className="text-green-400 font-mono">{msg.latency.tts_ms}ms</div>
              </div>
              <div>
                <div className="text-gray-400 mb-1">Total</div>
                <div className={`font-mono font-bold ${
                  msg.latency.total_ms < 3000 ? 'text-green-400' :
                  msg.latency.total_ms < 6000 ? 'text-yellow-400' : 'text-red-400'
                }`}>{msg.latency.total_ms}ms</div>
              </div>
            </div>
            {msg.latency.audio_duration_ms > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-700 text-gray-400">
                Audio duration: {(msg.latency.audio_duration_ms / 1000).toFixed(1)}s
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Transcript({ messages, isActive }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden h-[500px] flex flex-col shadow-xl">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
        <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <MessageCircle size={16} className="text-white" />
        </div>
        <h2 className="font-semibold text-white">Live Transcript</h2>
        {isActive && (
          <span className="ml-auto text-xs text-green-400 flex items-center gap-1.5 bg-green-900/30 px-2 py-1 rounded-full">
            <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse shadow-lg shadow-green-400/50" />
            Live
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 py-12">
            <MessageCircle size={32} className="mx-auto mb-2 opacity-50" />
            <p className="text-sm">
              {isActive ? 'Waiting for conversation...' : 'Start a call to begin'}
            </p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} index={i} />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
