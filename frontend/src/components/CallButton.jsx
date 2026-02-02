import React from 'react'
import { Phone, PhoneOff, Loader2 } from 'lucide-react'

export default function CallButton({ isActive, onStart, onEnd, disabled }) {
  if (isActive) {
    return (
      <button
        onClick={onEnd}
        className="relative flex items-center gap-2 px-6 py-2.5 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white font-medium rounded-xl shadow-lg shadow-red-500/25 hover:shadow-red-500/40 transition-all hover:scale-[1.02] active:scale-[0.98]"
      >
        {/* Animated ring for active call */}
        <span className="absolute -inset-1 bg-red-500/20 rounded-xl animate-pulse" />
        <PhoneOff size={18} className="relative" />
        <span className="relative">End Call</span>
      </button>
    )
  }

  if (disabled) {
    return (
      <button
        disabled
        className="flex items-center gap-2 px-6 py-2.5 bg-gray-700 text-gray-400 font-medium rounded-xl cursor-not-allowed"
      >
        <Loader2 size={18} className="animate-spin" />
        Loading...
      </button>
    )
  }

  return (
    <button
      onClick={onStart}
      className="flex items-center gap-2 px-6 py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-medium rounded-xl shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 transition-all hover:scale-[1.02] active:scale-[0.98]"
    >
      <Phone size={18} />
      Start Call
    </button>
  )
}
