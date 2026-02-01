import React from 'react'
import { Brain, ArrowRight, UserCheck, Clock, XCircle } from 'lucide-react'

const AGENTS = {
  router: { name: 'Router', icon: '&#128256;', color: 'bg-purple-500' },
  faq: { name: 'FAQ', icon: '&#128218;', color: 'bg-blue-500' },
  booking: { name: 'Booking', icon: '&#128197;', color: 'bg-green-500' },
  escalation: { name: 'Escalation', icon: '&#128100;', color: 'bg-orange-500' },
  response: { name: 'Response', icon: '&#128172;', color: 'bg-teal-500' }
}

const HUMAN_STATUS_CONFIG = {
  checking: {
    label: 'Checking availability...',
    icon: Clock,
    bgColor: 'bg-orange-900/30',
    borderColor: 'border-orange-700',
    textColor: 'text-orange-300',
    iconColor: 'text-orange-400'
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
  const currentAgent = AGENTS[state.currentAgent] || AGENTS.router

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <Brain size={18} className="text-purple-400" />
        <h2 className="font-semibold">Agent State</h2>
      </div>

      <div className="p-4 space-y-4">
        {/* Agent Pipeline */}
        <div className="flex items-center justify-between overflow-x-auto pb-2">
          {Object.entries(AGENTS).map(([key, agent], i) => (
            <React.Fragment key={key}>
              <div className={`flex flex-col items-center transition-all ${
                state.currentAgent === key ? 'scale-110' : 'opacity-40'
              }`}>
                <div className={`w-10 h-10 rounded-lg ${agent.color} flex items-center justify-center ${
                  state.currentAgent === key ? 'ring-2 ring-white' : ''
                }`}>
                  <span dangerouslySetInnerHTML={{ __html: agent.icon }} />
                </div>
                <span className="text-xs mt-1">{agent.name}</span>
              </div>
              {i < Object.keys(AGENTS).length - 1 && (
                <ArrowRight size={14} className="text-gray-600 flex-shrink-0" />
              )}
            </React.Fragment>
          ))}
        </div>

        {/* Intent */}
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="text-xs text-gray-400 mb-1">Detected Intent</div>
          <div className="flex items-center gap-2">
            {state.intent ? (
              <>
                <span className="px-2 py-1 bg-indigo-600 rounded text-xs font-medium uppercase">
                  {state.intent}
                </span>
                <span className="text-sm text-gray-300">
                  {INTENTS[state.intent] || state.intent}
                </span>
              </>
            ) : (
              <span className="text-gray-500 text-sm">Waiting for input...</span>
            )}
          </div>
        </div>

        {/* Confidence */}
        {state.confidence > 0 && (
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="text-xs text-gray-400 mb-2">Confidence</div>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-500 rounded-full transition-all"
                  style={{ width: `${state.confidence * 100}%` }}
                />
              </div>
              <span className="text-sm font-medium">
                {Math.round(state.confidence * 100)}%
              </span>
            </div>
          </div>
        )}

        {/* Escalation Status */}
        {state.escalationInProgress && (
          <EscalationStatus status={state.humanAgentStatus} />
        )}
      </div>
    </div>
  )
}

function EscalationStatus({ status }) {
  // Default to 'checking' if escalation is in progress but no status yet
  const statusKey = status || 'checking'
  const config = HUMAN_STATUS_CONFIG[statusKey] || HUMAN_STATUS_CONFIG.checking
  const IconComponent = config.icon

  return (
    <div className={`${config.bgColor} border ${config.borderColor} rounded-lg p-3`}>
      <div className="flex items-center gap-3">
        <div className={`${config.iconColor}`}>
          <IconComponent size={20} className={statusKey === 'checking' ? 'animate-spin' : ''} />
        </div>
        <div className="flex-1">
          <div className={`text-sm font-medium ${config.textColor}`}>
            Human Escalation
          </div>
          <div className={`text-xs ${config.textColor} opacity-80`}>
            {config.label}
          </div>
        </div>
        {statusKey === 'checking' && (
          <div className="flex gap-1">
            <div className="w-2 h-2 rounded-full bg-orange-400 animate-bounce" style={{ animationDelay: '0ms' }} />
            <div className="w-2 h-2 rounded-full bg-orange-400 animate-bounce" style={{ animationDelay: '150ms' }} />
            <div className="w-2 h-2 rounded-full bg-orange-400 animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        )}
      </div>
    </div>
  )
}
