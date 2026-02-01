import React, { useRef, useEffect } from 'react'
import { MessageCircle } from 'lucide-react'

export default function Transcript({ messages, isActive }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden h-[500px] flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <MessageCircle size={18} className="text-indigo-400" />
        <h2 className="font-semibold">Live Transcript</h2>
        {isActive && (
          <span className="ml-auto text-xs text-green-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
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
            <div
              key={i}
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
                    : 'bg-gray-800 rounded-bl-md'
                }`}>
                  <p className="text-sm">{msg.content}</p>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {msg.timestamp}
                  {msg.agentType && msg.role !== 'user' && (
                    <span className="ml-2 text-indigo-400">{'\u2022'} {msg.agentType}</span>
                  )}
                </p>
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
