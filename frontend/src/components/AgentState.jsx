import React from 'react'
import { Brain, UserCheck, Clock, XCircle, Bot } from 'lucide-react'

const HUMAN_STATUS_CONFIG = {
  initiated: {
    label: 'Initiating call...',
    icon: Clock,
    bgColor: 'bg-blue-900/30',
    borderColor: 'border-blue-700',
    textColor: 'text-blue-300',
    iconColor: 'text-blue-400'
  },
  checking: {
    label: 'Checking availability...',
    icon: Clock,
    bgColor: 'bg-orange-900/30',
    borderColor: 'border-orange-700',
    textColor: 'text-orange-300',
    iconColor: 'text-orange-400'
  },
  calling: {
    label: 'Calling team member...',
    icon: Clock,
    bgColor: 'bg-blue-900/30',
    borderColor: 'border-blue-700',
    textColor: 'text-blue-300',
    iconColor: 'text-blue-400'
  },
  ringing: {
    label: 'Phone ringing...',
    icon: Clock,
    bgColor: 'bg-indigo-900/30',
    borderColor: 'border-indigo-700',
    textColor: 'text-indigo-300',
    iconColor: 'text-indigo-400'
  },
  answered: {
    label: 'Human answered, connecting...',
    icon: UserCheck,
    bgColor: 'bg-green-900/30',
    borderColor: 'border-green-700',
    textColor: 'text-green-300',
    iconColor: 'text-green-400'
  },
  connected: {
    label: 'Human agent connected',
    icon: UserCheck,
    bgColor: 'bg-green-900/30',
    borderColor: 'border-green-700',
    textColor: 'text-green-300',
    iconColor: 'text-green-400'
  },
  unavailable: {
    label: 'Human agents unavailable',
    icon: XCircle,
    bgColor: 'bg-red-900/30',
    borderColor: 'border-red-700',
    textColor: 'text-red-300',
    iconColor: 'text-red-400'
  },
  busy: {
    label: 'Team member busy',
    icon: XCircle,
    bgColor: 'bg-orange-900/30',
    borderColor: 'border-orange-700',
    textColor: 'text-orange-300',
    iconColor: 'text-orange-400'
  },
  'no-answer': {
    label: 'No answer',
    icon: XCircle,
    bgColor: 'bg-yellow-900/30',
    borderColor: 'border-yellow-700',
    textColor: 'text-yellow-300',
    iconColor: 'text-yellow-400'
  },
  failed: {
    label: 'Could not connect',
    icon: XCircle,
    bgColor: 'bg-red-900/30',
    borderColor: 'border-red-700',
    textColor: 'text-red-300',
    iconColor: 'text-red-400'
  },
  returned_to_ai: {
    label: 'Returned to AI assistant',
    icon: Bot,
    bgColor: 'bg-gray-800/50',
    borderColor: 'border-gray-600',
    textColor: 'text-gray-300',
    iconColor: 'text-gray-400'
  }
}

const INTENTS = {
  faq: 'FAQ Question',
  book_service: 'Book Service',
  book_test_drive: 'Book Test Drive',
  reschedule: 'Reschedule',
  cancel: 'Cancel',
  escalation: 'Human Request',
  greeting: 'Greeting',
  goodbye: 'Goodbye',
  general: 'General'
}

export default function AgentState({ state }) {
  return (
    <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
        <div className="w-8 h-8 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-lg flex items-center justify-center shadow-lg shadow-purple-500/20">
          <Brain size={16} className="text-white" />
        </div>
        <h2 className="font-semibold text-white">Agent State</h2>
      </div>

      <div className="p-5 space-y-4">
        {/* Unified Agent Status */}
        <div className="flex items-center gap-3 p-4 bg-gradient-to-r from-purple-900/20 to-blue-900/20 rounded-xl border border-purple-700/30 shadow-inner">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center shadow-lg shadow-purple-500/30">
            <Bot size={24} className="text-white" />
          </div>
          <div>
            <div className="font-medium text-white">Unified Agent</div>
            <div className="text-xs text-gray-400">Handles FAQ, Booking, Escalation</div>
          </div>
          <div className="ml-auto">
            <div className="w-3 h-3 rounded-full bg-green-400 animate-pulse shadow-lg shadow-green-400/50" />
          </div>
        </div>

        {/* Current Activity */}
        {state.intent && (
          <div className="bg-gray-800/50 rounded-xl p-4">
            <div className="text-xs text-gray-400 mb-2 uppercase tracking-wide">Current Activity</div>
            <div className="flex items-center gap-2">
              <span className="px-3 py-1.5 bg-gradient-to-r from-indigo-600 to-purple-600 rounded-lg text-xs font-medium uppercase shadow-lg shadow-indigo-500/20">
                {state.intent}
              </span>
              <span className="text-sm text-gray-300">
                {INTENTS[state.intent] || state.intent}
              </span>
            </div>
          </div>
        )}

        {/* Confidence (if available) */}
        {state.confidence > 0 && (
          <div className="bg-gray-800/50 rounded-xl p-4">
            <div className="text-xs text-gray-400 mb-3 uppercase tracking-wide">Intent Confidence</div>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-2.5 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    state.confidence >= 0.8 ? 'bg-gradient-to-r from-green-500 to-emerald-500' :
                    state.confidence >= 0.6 ? 'bg-gradient-to-r from-indigo-500 to-purple-500' :
                    'bg-gradient-to-r from-yellow-500 to-orange-500'
                  }`}
                  style={{ width: `${state.confidence * 100}%` }}
                />
              </div>
              <span className={`text-sm font-bold ${
                state.confidence >= 0.8 ? 'text-green-400' :
                state.confidence >= 0.6 ? 'text-indigo-400' :
                'text-yellow-400'
              }`}>
                {Math.round(state.confidence * 100)}%
              </span>
            </div>
          </div>
        )}

        {/* Escalation Status - show when in progress OR when there's a recent status */}
        {(state.escalationInProgress || state.humanAgentStatus) && (
          <EscalationStatus status={state.humanAgentStatus} />
        )}
      </div>
    </div>
  )
}

// Updated human status config with better colors

function EscalationStatus({ status }) {
  const statusKey = status || 'checking'
  const config = HUMAN_STATUS_CONFIG[statusKey] || HUMAN_STATUS_CONFIG.checking
  const IconComponent = config.icon
  const isInProgress = ['checking', 'calling', 'ringing'].includes(statusKey)

  return (
    <div className={`${config.bgColor} border ${config.borderColor} rounded-lg p-3`}>
      <div className="flex items-center gap-3">
        <div className={`${config.iconColor}`}>
          <IconComponent size={20} className={isInProgress ? 'animate-spin' : ''} />
        </div>
        <div className="flex-1">
          <div className={`text-sm font-medium ${config.textColor}`}>
            Human Escalation
          </div>
          <div className={`text-xs ${config.textColor} opacity-80`}>
            {config.label}
          </div>
        </div>
        {isInProgress && (
          <div className="flex gap-1">
            <div className={`w-2 h-2 rounded-full ${config.iconColor.replace('text-', 'bg-')} animate-bounce`} style={{ animationDelay: '0ms' }} />
            <div className={`w-2 h-2 rounded-full ${config.iconColor.replace('text-', 'bg-')} animate-bounce`} style={{ animationDelay: '150ms' }} />
            <div className={`w-2 h-2 rounded-full ${config.iconColor.replace('text-', 'bg-')} animate-bounce`} style={{ animationDelay: '300ms' }} />
          </div>
        )}
      </div>
    </div>
  )
}
