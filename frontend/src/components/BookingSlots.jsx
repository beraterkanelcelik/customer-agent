import React from 'react'
import { Calendar, Check, Circle, CheckCircle2, Loader2 } from 'lucide-react'

// Slots in the order they should be collected (customer-first approach)
const SLOT_ORDER = [
  'customer_name',
  'customer_phone',
  'customer_email',
  'appointment_type',
  'service_type',
  'vehicle_interest',
  'preferred_date',
  'preferred_time'
]

const SLOT_LABELS = {
  customer_name: 'Name',
  customer_phone: 'Phone',
  customer_email: 'Email',
  appointment_type: 'Type',
  service_type: 'Service',
  vehicle_interest: 'Vehicle',
  preferred_date: 'Date',
  preferred_time: 'Time'
}

// Intents that indicate booking is happening
const BOOKING_INTENTS = ['book_service', 'book_test_drive', 'reschedule']

export default function BookingSlots({ slots, confirmedAppointment, intent, bookingInProgress }) {
  const hasAnySlot = Object.values(slots || {}).some(v => v !== null && v !== undefined)
  const isBookingIntent = BOOKING_INTENTS.includes(intent)
  // Show booking panel if: bookingInProgress flag is set OR has any slot OR booking intent
  const shouldShowBooking = bookingInProgress || hasAnySlot || isBookingIntent

  // Calculate progress
  const getFilledCount = () => {
    if (!slots) return 0
    const relevantSlots = SLOT_ORDER.filter(key => {
      // Skip service_type if test_drive, skip vehicle_interest if service
      if (key === 'service_type' && slots.appointment_type === 'test_drive') return false
      if (key === 'vehicle_interest' && slots.appointment_type === 'service') return false
      // Skip both if no appointment type yet
      if ((key === 'service_type' || key === 'vehicle_interest') && !slots.appointment_type) return false
      return true
    })
    return relevantSlots.filter(key => slots[key] !== null && slots[key] !== undefined).length
  }

  const getTotalCount = () => {
    if (!slots) return 7
    // Customer (3) + Type (1) + Detail (1) + Date (1) + Time (1) = 7
    return 7
  }

  const filledCount = getFilledCount()
  const totalCount = getTotalCount()
  const progressPercent = totalCount > 0 ? Math.round((filledCount / totalCount) * 100) : 0

  // Show confirmed appointment if available
  if (confirmedAppointment) {
    return (
      <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 bg-gradient-to-r from-green-900/50 to-emerald-900/30 border-b border-green-700/50 flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-br from-green-500 to-emerald-600 rounded-lg flex items-center justify-center shadow-lg shadow-green-500/30">
            <CheckCircle2 size={16} className="text-white" />
          </div>
          <h2 className="font-semibold text-green-300">Booking Confirmed!</h2>
        </div>

        <div className="p-5 space-y-4">
          <div className="bg-gradient-to-r from-green-900/30 to-emerald-900/20 rounded-xl p-4 border border-green-700/30">
            <div className="text-xs text-green-400 uppercase tracking-wide mb-1">Confirmation #</div>
            <div className="text-3xl font-bold bg-gradient-to-r from-green-300 to-emerald-300 bg-clip-text text-transparent">{confirmedAppointment.appointment_id}</div>
          </div>

          <div className="space-y-2 text-sm">
            <div className="flex justify-between py-2 border-b border-gray-800">
              <span className="text-gray-400">Type</span>
              <span className="text-white font-medium capitalize">{confirmedAppointment.appointment_type?.replace('_', ' ')}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-gray-800">
              <span className="text-gray-400">Date</span>
              <span className="text-white font-medium">{confirmedAppointment.scheduled_date}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-gray-800">
              <span className="text-gray-400">Time</span>
              <span className="text-white font-medium">{confirmedAppointment.scheduled_time}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-gray-800">
              <span className="text-gray-400">Customer</span>
              <span className="text-white font-medium">{confirmedAppointment.customer_name}</span>
            </div>
            {confirmedAppointment.service_type && (
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Service</span>
                <span className="text-white font-medium">{confirmedAppointment.service_type}</span>
              </div>
            )}
            {confirmedAppointment.vehicle && (
              <div className="flex justify-between py-2 border-b border-gray-800">
                <span className="text-gray-400">Vehicle</span>
                <span className="text-white font-medium">{confirmedAppointment.vehicle}</span>
              </div>
            )}
          </div>

          {confirmedAppointment.confirmation_email && (
            <div className="text-xs text-gray-400 mt-3 p-2 bg-gray-800 rounded">
              Confirmation sent to: {confirmedAppointment.confirmation_email}
            </div>
          )}
        </div>
      </div>
    )
  }

  // Show panel if: confirmed appointment, bookingInProgress, has any slot, OR booking intent detected
  const shouldShowPanel = confirmedAppointment || shouldShowBooking

  if (!shouldShowPanel) {
    return (
      <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-br from-green-500 to-emerald-600 rounded-lg flex items-center justify-center shadow-lg shadow-green-500/20">
            <Calendar size={16} className="text-white" />
          </div>
          <h2 className="font-semibold text-white">Booking Info</h2>
        </div>
        <div className="p-5 text-center text-gray-500 py-8">
          <Calendar size={32} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">No booking in progress</p>
        </div>
      </div>
    )
  }

  // Show booking in progress (booking started but no slots yet)
  if (shouldShowBooking && !hasAnySlot) {
    return (
      <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 bg-gradient-to-r from-indigo-900/50 to-purple-900/30 border-b border-indigo-700/50 flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Loader2 size={16} className="text-white animate-spin" />
          </div>
          <h2 className="font-semibold text-indigo-300">Starting Booking...</h2>
        </div>
        <div className="p-5">
          <div className="text-sm text-gray-400 mb-4">Collecting your information</div>
          {/* Progress bar - starts at 0 */}
          <div className="mb-5">
            <div className="flex justify-between text-xs text-gray-500 mb-2">
              <span>Progress</span>
              <span>0 / {totalCount}</span>
            </div>
            <div className="h-2.5 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-300" style={{ width: '0%' }} />
            </div>
          </div>
          <div className="space-y-2 opacity-50">
            {SLOT_ORDER.slice(0, 5).map(key => (
              <div key={key} className="flex items-center justify-between py-2.5 border-b border-gray-800/50 last:border-0">
                <span className="text-sm text-gray-500">{SLOT_LABELS[key]}</span>
                <span className="text-sm text-gray-600 flex items-center gap-1">
                  <Circle size={10} />
                  &#8212;
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Determine which slots to show based on appointment type
  const getSlotsToShow = () => {
    const apptType = slots?.appointment_type
    return SLOT_ORDER.filter(key => {
      // Always show customer info
      if (['customer_name', 'customer_phone', 'customer_email'].includes(key)) return true
      // Always show appointment type
      if (key === 'appointment_type') return true
      // Show service_type only for service appointments
      if (key === 'service_type') return !apptType || apptType === 'service'
      // Show vehicle_interest only for test drives
      if (key === 'vehicle_interest') return !apptType || apptType === 'test_drive'
      // Always show date/time
      return true
    })
  }

  return (
    <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
      <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
        <div className="w-8 h-8 bg-gradient-to-br from-green-500 to-emerald-600 rounded-lg flex items-center justify-center shadow-lg shadow-green-500/20">
          <Calendar size={16} className="text-white" />
        </div>
        <h2 className="font-semibold text-white">Booking Info</h2>
      </div>

      <div className="p-5">
        {/* Progress bar */}
        <div className="mb-5">
          <div className="flex justify-between text-xs text-gray-500 mb-2">
            <span>Progress</span>
            <span className="font-medium">{filledCount} / {totalCount}</span>
          </div>
          <div className="h-2.5 bg-gray-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                progressPercent === 100
                  ? 'bg-gradient-to-r from-green-500 to-emerald-500'
                  : 'bg-gradient-to-r from-indigo-500 to-purple-500'
              }`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {/* Slot list */}
        <div className="space-y-1">
          {getSlotsToShow().map((key) => {
            const label = SLOT_LABELS[key]
            const value = slots[key]
            const hasValue = value !== null && value !== undefined

            return (
              <div
                key={key}
                className={`flex items-center justify-between py-2.5 px-3 rounded-lg transition-all ${
                  hasValue ? 'bg-green-900/20' : 'hover:bg-gray-800/30'
                }`}
              >
                <span className="text-sm text-gray-400">{label}</span>
                {hasValue ? (
                  <span className="text-sm font-medium text-green-400 flex items-center gap-1.5">
                    <Check size={14} className="text-green-500" />
                    {String(value)}
                  </span>
                ) : (
                  <span className="text-sm text-gray-600 flex items-center gap-1">
                    <Circle size={10} className="opacity-50" />
                    <span className="text-gray-600">&#8212;</span>
                  </span>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
