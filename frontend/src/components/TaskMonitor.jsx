import React from 'react'
import { Zap, Check, Loader2, XCircle } from 'lucide-react'

const STATUS_CONFIG = {
  pending: { icon: Loader2, color: 'text-yellow-400', bg: 'bg-yellow-900/30' },
  running: { icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-900/30', spin: true },
  completed: { icon: Check, color: 'text-green-400', bg: 'bg-green-900/30' },
  failed: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-900/30' }
}

export default function TaskMonitor({ tasks }) {
  const activeTasks = tasks.filter(t => t.status !== 'completed' && t.status !== 'failed')
  const hasActive = activeTasks.length > 0

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <Zap size={18} className="text-yellow-400" />
        <h2 className="font-semibold">Background Tasks</h2>
        {hasActive && (
          <span className="ml-auto text-xs bg-yellow-600 px-2 py-0.5 rounded-full">
            {activeTasks.length} active
          </span>
        )}
      </div>

      <div className="p-4">
        {tasks.length === 0 ? (
          <div className="text-center text-gray-500 py-6">
            <Zap size={24} className="mx-auto mb-2 opacity-50" />
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
                  className={`${config.bg} border border-gray-700 rounded-lg p-3`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Icon
                      size={16}
                      className={`${config.color} ${config.spin ? 'animate-spin' : ''}`}
                    />
                    <span className="text-sm font-medium">
                      {task.task_type.replace('_', ' ')}
                    </span>
                  </div>
                  <div className="text-xs text-gray-400">
                    Status: {task.status}
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
