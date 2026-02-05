import React from 'react'
import { Calendar, Check, Circle, CheckCircle2, Loader2, Sparkles } from 'lucide-react'

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
      <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in-scale">
        <div className="px-5 py-4 bg-gradient-to-r from-success-50 to-success-100/50 border-b border-success-200/50 flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-success-400 to-success-500 rounded-xl flex items-center justify-center shadow-glow-success">
            <CheckCircle2 size={18} className="text-white" />
          </div>
          <div>
            <h2 className="font-semibold text-success-800 flex items-center gap-2">
              Booking Confirmed!
              <Sparkles size={14} className="text-success-500" />
            </h2>
            <p className="text-xs text-success-600">Appointment scheduled successfully</p>
          </div>
        </div>

        <div className="p-5 space-y-4">
          <div className="bg-gradient-to-r from-success-50 to-success-100/50 rounded-2xl p-5 border border-success-200/50">
            <div className="text-[10px] text-success-600 uppercase tracking-wider font-medium mb-1">Confirmation #</div>
            <div className="text-3xl font-bold text-success-700 font-mono">{confirmedAppointment.appointment_id}</div>
          </div>

          <div className="space-y-1 text-sm">
            {[
              { label: 'Type', value: confirmedAppointment.appointment_type?.replace('_', ' ') },
              { label: 'Date', value: confirmedAppointment.scheduled_date },
              { label: 'Time', value: confirmedAppointment.scheduled_time },
              { label: 'Customer', value: confirmedAppointment.customer_name },
              { label: 'Service', value: confirmedAppointment.service_type },
              { label: 'Vehicle', value: confirmedAppointment.vehicle }
            ].filter(item => item.value).map((item, i) => (
              <div key={item.label} className="flex justify-between py-3 border-b border-surface-200 last:border-0 animate-fade-in" style={{ animationDelay: `${i * 0.05}s` }}>
                <span className="text-slate-500">{item.label}</span>
                <span className="text-slate-800 font-medium capitalize">{item.value}</span>
              </div>
            ))}
          </div>

          {confirmedAppointment.confirmation_email && (
            <div className="text-xs text-slate-500 mt-3 p-3 bg-surface-100/50 rounded-xl border border-surface-200 flex items-center gap-2">
              <Check size={14} className="text-success-500" />
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
      <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg">
        <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-success-400 to-success-500 rounded-xl flex items-center justify-center shadow-soft">
            <Calendar size={18} className="text-white" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-800">Booking Info</h2>
            <p className="text-xs text-slate-400">Appointment details</p>
          </div>
        </div>
        <div className="p-8 text-center">
          <div className="w-16 h-16 mx-auto mb-4 bg-surface-200/50 rounded-2xl flex items-center justify-center">
            <Calendar size={28} className="text-slate-300" />
          </div>
          <p className="text-sm text-slate-500 font-medium">No booking in progress</p>
          <p className="text-xs text-slate-400 mt-1">Start by asking to book an appointment</p>
        </div>
      </div>
    )
  }

  // Show booking in progress (booking started but no slots yet)
  if (shouldShowBooking && !hasAnySlot) {
    return (
      <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in">
        <div className="px-5 py-4 bg-gradient-to-r from-accent-50 to-soft-50 border-b border-accent-200/50 flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-accent-400 to-soft-500 rounded-xl flex items-center justify-center shadow-soft">
            <Loader2 size={18} className="text-white animate-spin" />
          </div>
          <div>
            <h2 className="font-semibold text-accent-800">Starting Booking...</h2>
            <p className="text-xs text-accent-600">Collecting your information</p>
          </div>
        </div>
        <div className="p-5">
          {/* Progress bar - starts at 0 */}
          <div className="mb-5">
            <div className="flex justify-between text-xs mb-2">
              <span className="text-slate-400 uppercase tracking-wide font-medium">Progress</span>
              <span className="text-slate-500 font-medium">0 / {totalCount}</span>
            </div>
            <div className="h-3 bg-surface-200 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-accent-400 to-soft-500 rounded-full transition-all duration-500 shimmer" style={{ width: '0%' }} />
            </div>
          </div>
          <div className="space-y-2 opacity-50">
            {SLOT_ORDER.slice(0, 5).map((key, i) => (
              <div key={key} className="flex items-center justify-between py-3 px-4 bg-white/40 rounded-xl border border-surface-200" style={{ animationDelay: `${i * 0.1}s` }}>
                <span className="text-sm text-slate-400">{SLOT_LABELS[key]}</span>
                <span className="text-sm text-slate-300 flex items-center gap-2">
                  <Circle size={10} className="opacity-50" />
                  <span>—</span>
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
    <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg">
      <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
        <div className="w-10 h-10 bg-gradient-to-br from-success-400 to-success-500 rounded-xl flex items-center justify-center shadow-soft">
          <Calendar size={18} className="text-white" />
        </div>
        <div>
          <h2 className="font-semibold text-slate-800">Booking Info</h2>
          <p className="text-xs text-slate-400">Appointment details</p>
        </div>
      </div>

      <div className="p-5">
        {/* Progress bar */}
        <div className="mb-5">
          <div className="flex justify-between text-xs mb-2">
            <span className="text-slate-400 uppercase tracking-wide font-medium">Progress</span>
            <span className="text-slate-600 font-semibold">{filledCount} / {totalCount}</span>
          </div>
          <div className="h-3 bg-surface-200 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ease-out ${
                progressPercent === 100
                  ? 'bg-gradient-to-r from-success-400 to-success-500'
                  : 'bg-gradient-to-r from-accent-400 to-soft-500'
              }`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {/* Slot list */}
        <div className="space-y-2">
          {getSlotsToShow().map((key, i) => {
            const label = SLOT_LABELS[key]
            const value = slots[key]
            const hasValue = value !== null && value !== undefined

            return (
              <div
                key={key}
                className={`flex items-center justify-between py-3 px-4 rounded-xl transition-all duration-300 animate-fade-in ${
                  hasValue
                    ? 'bg-success-50/80 border border-success-200'
                    : 'bg-white/40 border border-surface-200 hover:bg-white/60'
                }`}
                style={{ animationDelay: `${i * 0.05}s` }}
              >
                <span className={`text-sm ${hasValue ? 'text-success-700' : 'text-slate-500'}`}>{label}</span>
                {hasValue ? (
                  <span className="text-sm font-medium text-success-700 flex items-center gap-2">
                    <Check size={14} className="text-success-500" />
                    {String(value)}
                  </span>
                ) : (
                  <span className="text-sm text-slate-300 flex items-center gap-2">
                    <Circle size={10} className="opacity-50" />
                    <span>—</span>
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
