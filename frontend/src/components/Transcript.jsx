import React, { useRef, useEffect, useState } from 'react'
import { MessageCircle, Clock, ChevronDown, ChevronUp, User, Bot } from 'lucide-react'

// Message bubble with collapsible latency details
function MessageBubble({ msg, index }) {
  const [expanded, setExpanded] = useState(false)
  const hasLatency = msg.latency && msg.role === 'assistant'

  return (
    <div
      className={`flex gap-3 message-enter ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
      style={{ animationDelay: `${index * 0.05}s` }}
    >
      {/* Avatar */}
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 shadow-sm transition-transform duration-200 hover:scale-105 ${
        msg.role === 'user'
          ? 'bg-gradient-to-br from-soft-400 to-soft-500'
          : 'bg-gradient-to-br from-accent-400 to-accent-500'
      }`}>
        {msg.role === 'user' ? (
          <User size={16} className="text-white" />
        ) : (
          <Bot size={16} className="text-white" />
        )}
      </div>

      {/* Message */}
      <div className={`flex-1 ${msg.role === 'user' ? 'text-right' : ''}`}>
        <div className={`inline-block px-4 py-3 rounded-2xl max-w-[85%] transition-all duration-200 ${
          msg.role === 'user'
            ? 'bg-gradient-to-br from-soft-500 to-soft-600 text-white rounded-br-md shadow-soft'
            : msg.isSystemMessage
              ? 'bg-surface-200/80 border border-surface-300 rounded-bl-md text-slate-600'
              : 'bg-white/80 border border-surface-200 rounded-bl-md shadow-glass text-slate-700'
        }`}>
          <p className="text-sm leading-relaxed">{msg.content}</p>
        </div>

        {/* Timestamp and agent type */}
        <div className={`text-xs text-slate-400 mt-2 flex items-center gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <span className="font-medium">{msg.timestamp}</span>
          {msg.agentType && msg.role !== 'user' && (
            <span className="text-accent-500 flex items-center gap-1">
              <span className="w-1 h-1 rounded-full bg-accent-400" />
              {msg.agentType}
            </span>
          )}

          {/* Latency toggle button */}
          {hasLatency && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1.5 text-slate-400 hover:text-accent-500 transition-colors px-2 py-0.5 rounded-md hover:bg-accent-50"
            >
              <Clock size={12} />
              <span className="font-mono">{(msg.latency.total_ms / 1000).toFixed(1)}s</span>
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          )}
        </div>

        {/* Expanded latency details */}
        {hasLatency && expanded && (
          <div className="mt-3 p-3 bg-surface-100/80 backdrop-blur-sm rounded-xl text-xs max-w-[85%] inline-block border border-surface-200 animate-fade-in">
            <div className="grid grid-cols-4 gap-3 text-center">
              <div className="p-2 bg-white/60 rounded-lg">
                <div className="text-slate-400 mb-1 uppercase tracking-wide text-[10px]">STT</div>
                <div className="text-soft-600 font-mono font-semibold">{msg.latency.stt_ms}ms</div>
              </div>
              <div className="p-2 bg-white/60 rounded-lg">
                <div className="text-slate-400 mb-1 uppercase tracking-wide text-[10px]">LLM</div>
                <div className="text-accent-600 font-mono font-semibold">{msg.latency.llm_ms}ms</div>
              </div>
              <div className="p-2 bg-white/60 rounded-lg">
                <div className="text-slate-400 mb-1 uppercase tracking-wide text-[10px]">TTS</div>
                <div className="text-success-600 font-mono font-semibold">{msg.latency.tts_ms}ms</div>
              </div>
              <div className="p-2 bg-white/60 rounded-lg">
                <div className="text-slate-400 mb-1 uppercase tracking-wide text-[10px]">Total</div>
                <div className={`font-mono font-bold ${
                  msg.latency.total_ms < 3000 ? 'text-success-600' :
                  msg.latency.total_ms < 6000 ? 'text-warning-600' : 'text-error-600'
                }`}>{msg.latency.total_ms}ms</div>
              </div>
            </div>
            {msg.latency.audio_duration_ms > 0 && (
              <div className="mt-3 pt-3 border-t border-surface-200 text-slate-500 text-center">
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
    <div className="glass-card rounded-3xl overflow-hidden h-[500px] flex flex-col shadow-glass-lg">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
        <div className="w-10 h-10 bg-gradient-to-br from-accent-400 to-soft-500 rounded-xl flex items-center justify-center shadow-soft">
          <MessageCircle size={18} className="text-white" />
        </div>
        <div>
          <h2 className="font-semibold text-slate-800">Live Transcript</h2>
          <p className="text-xs text-slate-400">Real-time conversation</p>
        </div>
        {isActive && (
          <span className="ml-auto flex items-center gap-2 text-xs text-success-600 bg-success-50 px-3 py-1.5 rounded-full border border-success-200">
            <span className="w-2 h-2 bg-success-500 rounded-full status-dot status-dot-success" />
            <span className="font-medium">Live</span>
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5 bg-gradient-to-b from-transparent to-surface-50/30">
        {messages.length === 0 ? (
          <div className="text-center py-16 animate-fade-in">
            <div className="w-16 h-16 mx-auto mb-4 bg-surface-200/50 rounded-2xl flex items-center justify-center">
              <MessageCircle size={28} className="text-slate-300" />
            </div>
            <p className="text-sm text-slate-500 font-medium">
              {isActive ? 'Waiting for conversation...' : 'Start a call to begin'}
            </p>
            <p className="text-xs text-slate-400 mt-1">
              Messages will appear here in real-time
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
