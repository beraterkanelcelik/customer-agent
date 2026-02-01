import React from 'react'
import { Calendar, Check, Circle } from 'lucide-react'

const SLOT_LABELS = {
  appointment_type: 'Type',
  service_type: 'Service',
  vehicle_interest: 'Vehicle',
  preferred_date: 'Date',
  preferred_time: 'Time',
  customer_name: 'Name',
  customer_phone: 'Phone',
  customer_email: 'Email'
}

export default function BookingSlots({ slots }) {
  const hasAnySlot = Object.values(slots || {}).some(v => v !== null && v !== undefined)

  if (!hasAnySlot) {
    return (
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
          <Calendar size={18} className="text-green-400" />
          <h2 className="font-semibold">Booking Info</h2>
        </div>
        <div className="p-4 text-center text-gray-500 py-8">
          <Calendar size={28} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No booking in progress</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <Calendar size={18} className="text-green-400" />
        <h2 className="font-semibold">Booking Info</h2>
      </div>

      <div className="p-4 space-y-2">
        {Object.entries(SLOT_LABELS).map(([key, label]) => {
          const value = slots[key]
          const hasValue = value !== null && value !== undefined

          return (
            <div
              key={key}
              className="flex items-center justify-between py-2 border-b border-gray-800 last:border-0"
            >
              <span className="text-sm text-gray-400">{label}</span>
              {hasValue ? (
                <span className="text-sm font-medium text-green-400 flex items-center gap-1">
                  <Check size={14} />
                  {String(value)}
                </span>
              ) : (
                <span className="text-sm text-gray-600 flex items-center gap-1">
                  <Circle size={10} />
                  &#8212;
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
