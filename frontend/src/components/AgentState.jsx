import React from 'react'
import { Brain, UserCheck, Clock, XCircle, Bot, Sparkles } from 'lucide-react'

const HUMAN_STATUS_CONFIG = {
  initiated: {
    label: 'Initiating call...',
    icon: Clock,
    bgColor: 'bg-soft-50',
    borderColor: 'border-soft-200',
    textColor: 'text-soft-700',
    iconColor: 'text-soft-500',
    iconBg: 'bg-soft-100'
  },
  checking: {
    label: 'Checking availability...',
    icon: Clock,
    bgColor: 'bg-warning-50',
    borderColor: 'border-warning-200',
    textColor: 'text-warning-700',
    iconColor: 'text-warning-500',
    iconBg: 'bg-warning-100'
  },
  calling: {
    label: 'Calling team member...',
    icon: Clock,
    bgColor: 'bg-soft-50',
    borderColor: 'border-soft-200',
    textColor: 'text-soft-700',
    iconColor: 'text-soft-500',
    iconBg: 'bg-soft-100'
  },
  ringing: {
    label: 'Phone ringing...',
    icon: Clock,
    bgColor: 'bg-accent-50',
    borderColor: 'border-accent-200',
    textColor: 'text-accent-700',
    iconColor: 'text-accent-500',
    iconBg: 'bg-accent-100'
  },
  waiting_confirmation: {
    label: 'Waiting for agent to accept...',
    icon: Clock,
    bgColor: 'bg-warning-50',
    borderColor: 'border-warning-200',
    textColor: 'text-warning-700',
    iconColor: 'text-warning-500',
    iconBg: 'bg-warning-100'
  },
  confirmed: {
    label: 'Agent accepted, connecting...',
    icon: UserCheck,
    bgColor: 'bg-success-50',
    borderColor: 'border-success-200',
    textColor: 'text-success-700',
    iconColor: 'text-success-500',
    iconBg: 'bg-success-100'
  },
  connected: {
    label: 'Human agent connected',
    icon: UserCheck,
    bgColor: 'bg-success-50',
    borderColor: 'border-success-200',
    textColor: 'text-success-700',
    iconColor: 'text-success-500',
    iconBg: 'bg-success-100'
  },
  unavailable: {
    label: 'Human agents unavailable',
    icon: XCircle,
    bgColor: 'bg-error-50',
    borderColor: 'border-error-200',
    textColor: 'text-error-700',
    iconColor: 'text-error-500',
    iconBg: 'bg-error-100'
  },
  busy: {
    label: 'Team member busy',
    icon: XCircle,
    bgColor: 'bg-warning-50',
    borderColor: 'border-warning-200',
    textColor: 'text-warning-700',
    iconColor: 'text-warning-500',
    iconBg: 'bg-warning-100'
  },
  'no-answer': {
    label: 'No answer',
    icon: XCircle,
    bgColor: 'bg-warning-50',
    borderColor: 'border-warning-200',
    textColor: 'text-warning-700',
    iconColor: 'text-warning-500',
    iconBg: 'bg-warning-100'
  },
  voicemail: {
    label: 'Went to voicemail',
    icon: XCircle,
    bgColor: 'bg-warning-50',
    borderColor: 'border-warning-200',
    textColor: 'text-warning-700',
    iconColor: 'text-warning-500',
    iconBg: 'bg-warning-100'
  },
  declined: {
    label: 'Agent declined call',
    icon: XCircle,
    bgColor: 'bg-warning-50',
    borderColor: 'border-warning-200',
    textColor: 'text-warning-700',
    iconColor: 'text-warning-500',
    iconBg: 'bg-warning-100'
  },
  failed: {
    label: 'Could not connect',
    icon: XCircle,
    bgColor: 'bg-error-50',
    borderColor: 'border-error-200',
    textColor: 'text-error-700',
    iconColor: 'text-error-500',
    iconBg: 'bg-error-100'
  },
  canceled: {
    label: 'Call rejected',
    icon: XCircle,
    bgColor: 'bg-warning-50',
    borderColor: 'border-warning-200',
    textColor: 'text-warning-700',
    iconColor: 'text-warning-500',
    iconBg: 'bg-warning-100'
  },
  returned_to_ai: {
    label: 'Returned to AI assistant',
    icon: Bot,
    bgColor: 'bg-surface-100',
    borderColor: 'border-surface-300',
    textColor: 'text-slate-600',
    iconColor: 'text-slate-500',
    iconBg: 'bg-surface-200'
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
    <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
        <div className="w-10 h-10 bg-gradient-to-br from-accent-400 to-soft-500 rounded-xl flex items-center justify-center shadow-soft">
          <Brain size={18} className="text-white" />
        </div>
        <div>
          <h2 className="font-semibold text-slate-800">Agent State</h2>
          <p className="text-xs text-slate-400">AI processing status</p>
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Unified Agent Status */}
        <div className="flex items-center gap-4 p-4 bg-gradient-to-r from-accent-50/50 to-soft-50/50 rounded-2xl border border-accent-100 transition-all duration-300 hover:shadow-soft">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-accent-400 to-soft-500 flex items-center justify-center shadow-soft">
            <Bot size={26} className="text-white" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-slate-800 flex items-center gap-2">
              Unified Agent
              <Sparkles size={14} className="text-accent-500" />
            </div>
            <div className="text-xs text-slate-500 mt-0.5">Handles FAQ, Booking, Escalation</div>
          </div>
          <div className="relative">
            <div className="w-3.5 h-3.5 rounded-full bg-success-400 shadow-glow-success" />
            <div className="absolute inset-0 w-3.5 h-3.5 rounded-full bg-success-400 animate-ping opacity-30" />
          </div>
        </div>

        {/* Current Activity */}
        {state.intent && (
          <div className="bg-white/60 backdrop-blur-sm rounded-2xl p-4 border border-surface-200 animate-fade-in">
            <div className="text-[10px] text-slate-400 mb-2 uppercase tracking-wider font-medium">Current Activity</div>
            <div className="flex items-center gap-3">
              <span className="px-3 py-1.5 bg-gradient-to-r from-accent-500 to-soft-500 rounded-lg text-xs font-semibold uppercase text-white shadow-soft">
                {state.intent}
              </span>
              <span className="text-sm text-slate-600 font-medium">
                {INTENTS[state.intent] || state.intent}
              </span>
            </div>
          </div>
        )}

        {/* Confidence (if available) */}
        {state.confidence > 0 && (
          <div className="bg-white/60 backdrop-blur-sm rounded-2xl p-4 border border-surface-200 animate-fade-in">
            <div className="text-[10px] text-slate-400 mb-3 uppercase tracking-wider font-medium">Intent Confidence</div>
            <div className="flex items-center gap-4">
              <div className="flex-1 h-3 bg-surface-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ease-out ${
                    state.confidence >= 0.8 ? 'bg-gradient-to-r from-success-400 to-success-500' :
                    state.confidence >= 0.6 ? 'bg-gradient-to-r from-accent-400 to-soft-500' :
                    'bg-gradient-to-r from-warning-400 to-warning-500'
                  }`}
                  style={{ width: `${state.confidence * 100}%` }}
                />
              </div>
              <span className={`text-sm font-bold min-w-[40px] text-right ${
                state.confidence >= 0.8 ? 'text-success-600' :
                state.confidence >= 0.6 ? 'text-accent-600' :
                'text-warning-600'
              }`}>
                {Math.round(state.confidence * 100)}%
              </span>
            </div>
          </div>
        )}

        {/* Escalation Status - only show when actively escalating or has meaningful status */}
        {/* Don't show for "none" or null/undefined status unless escalation is in progress */}
        {(state.escalationInProgress || (state.humanAgentStatus && state.humanAgentStatus !== 'none')) && (
          <EscalationStatus status={state.humanAgentStatus} />
        )}
      </div>
    </div>
  )
}

function EscalationStatus({ status }) {
  const statusKey = status || 'checking'
  const config = HUMAN_STATUS_CONFIG[statusKey] || HUMAN_STATUS_CONFIG.checking
  const IconComponent = config.icon
  const isInProgress = ['checking', 'calling', 'ringing', 'waiting_confirmation'].includes(statusKey)

  return (
    <div className={`${config.bgColor} border ${config.borderColor} rounded-2xl p-4 animate-fade-in-scale`}>
      <div className="flex items-center gap-4">
        <div className={`w-11 h-11 rounded-xl ${config.iconBg} flex items-center justify-center`}>
          <IconComponent size={20} className={`${config.iconColor} ${isInProgress ? 'animate-spin' : ''}`} />
        </div>
        <div className="flex-1">
          <div className={`text-sm font-semibold ${config.textColor}`}>
            Human Escalation
          </div>
          <div className={`text-xs ${config.textColor} opacity-70 mt-0.5`}>
            {config.label}
          </div>
        </div>
        {isInProgress && (
          <div className="flex gap-1.5">
            <div className={`w-2 h-2 rounded-full ${config.iconColor.replace('text-', 'bg-')} animate-bounce`} style={{ animationDelay: '0ms' }} />
            <div className={`w-2 h-2 rounded-full ${config.iconColor.replace('text-', 'bg-')} animate-bounce`} style={{ animationDelay: '150ms' }} />
            <div className={`w-2 h-2 rounded-full ${config.iconColor.replace('text-', 'bg-')} animate-bounce`} style={{ animationDelay: '300ms' }} />
          </div>
        )}
      </div>
    </div>
  )
}
