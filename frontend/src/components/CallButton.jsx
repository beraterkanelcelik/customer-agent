import React from 'react'
import { Phone, PhoneOff } from 'lucide-react'

export default function CallButton({ isActive, onStart, onEnd }) {
  return (
    <button
      onClick={isActive ? onEnd : onStart}
      className={`flex items-center gap-2 px-6 py-2.5 rounded-lg font-medium transition-all ${
        isActive
          ? 'bg-red-600 hover:bg-red-700 text-white'
          : 'bg-indigo-600 hover:bg-indigo-700 text-white'
      }`}
    >
      {isActive ? (
        <>
          <PhoneOff size={18} />
          End Call
        </>
      ) : (
        <>
          <Phone size={18} />
          Start Call
        </>
      )}
    </button>
  )
}
