import React from 'react'
import { Zap, Check, Loader2, XCircle } from 'lucide-react'

const STATUS_CONFIG = {
  pending: { icon: Loader2, color: 'text-yellow-400', bg: 'bg-yellow-900/20', border: 'border-yellow-700/30' },
  running: { icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-900/20', border: 'border-blue-700/30', spin: true },
  completed: { icon: Check, color: 'text-green-400', bg: 'bg-green-900/20', border: 'border-green-700/30' },
  failed: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-900/20', border: 'border-red-700/30' }
}

export default function TaskMonitor({ tasks }) {
  const activeTasks = tasks.filter(t => t.status !== 'completed' && t.status !== 'failed')
  const hasActive = activeTasks.length > 0

  return (
    <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
      <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
        <div className="w-8 h-8 bg-gradient-to-br from-yellow-500 to-orange-600 rounded-lg flex items-center justify-center shadow-lg shadow-yellow-500/20">
          <Zap size={16} className="text-white" />
        </div>
        <h2 className="font-semibold text-white">Background Tasks</h2>
        {hasActive && (
          <span className="ml-auto text-xs bg-gradient-to-r from-yellow-600 to-orange-600 px-2.5 py-1 rounded-full font-medium shadow-lg shadow-yellow-500/20">
            {activeTasks.length} active
          </span>
        )}
      </div>

      <div className="p-5">
        {tasks.length === 0 ? (
          <div className="text-center text-gray-500 py-6">
            <Zap size={28} className="mx-auto mb-3 opacity-40" />
            <p className="text-sm">No active tasks</p>
          </div>
        ) : (
          <div className="space-y-3">
            {tasks.map(task => {
              const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending
              const Icon = config.icon

              return (
                <div
                  key={task.task_id}
                  className={`${config.bg} border ${config.border} rounded-xl p-4`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Icon
                      size={16}
                      className={`${config.color} ${config.spin ? 'animate-spin' : ''}`}
                    />
                    <span className="text-sm font-medium capitalize">
                      {task.task_type.replace('_', ' ')}
                    </span>
                  </div>
                  <div className="text-xs text-gray-400">
                    Status: <span className="capitalize">{task.status}</span>
                  </div>
                  {task.human_agent_name && (
                    <div className="text-xs text-green-400 mt-1">
                      Agent: {task.human_agent_name}
                    </div>
                  )}
                  {task.callback_scheduled && (
                    <div className="text-xs text-yellow-400 mt-1">
                      Callback: {task.callback_scheduled}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
