import React, { useState, useEffect, useCallback } from 'react'
import { Calendar, Clock, ChevronLeft, ChevronRight, RefreshCw, Car } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function AvailabilityCalendar({ appointmentType = null, onSlotSelect = null, wsUpdate = null }) {
  const [availability, setAvailability] = useState(null)
  const [vehicles, setVehicles] = useState([])
  const [selectedVehicle, setSelectedVehicle] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedDate, setSelectedDate] = useState(null)
  const [weekOffset, setWeekOffset] = useState(0)

  // Process WebSocket updates from parent
  useEffect(() => {
    if (wsUpdate && wsUpdate.type === 'availability_update') {
      setAvailability(prev => {
        if (!prev) return prev

        return {
          ...prev,
          days: prev.days.map(day => {
            if (day.date !== wsUpdate.slot_date) return day

            return {
              ...day,
              slots: day.slots.map(slot => {
                if (slot.slot_time !== wsUpdate.slot_time) return slot
                // Match by inventory_id for test drives (if provided)
                if (wsUpdate.inventory_id && slot.inventory_id !== wsUpdate.inventory_id) return slot

                return {
                  ...slot,
                  is_available: wsUpdate.is_available
                }
              })
            }
          }),
          total_available: prev.total_available + (wsUpdate.is_available ? 1 : -1)
        }
      })
    }
  }, [wsUpdate])

  // Fetch available vehicles for test drives
  useEffect(() => {
    const fetchVehicles = async () => {
      try {
        const res = await fetch(`${API_URL}/api/availability/vehicles`)
        if (!res.ok) throw new Error('Failed to fetch vehicles')
        const data = await res.json()
        setVehicles(data.vehicles || [])
        // Auto-select first vehicle
        if (data.vehicles?.length > 0 && !selectedVehicle) {
          setSelectedVehicle(data.vehicles[0].id)
        }
      } catch (err) {
        console.error('Error fetching vehicles:', err)
      }
    }
    fetchVehicles()
  }, [])

  const fetchAvailability = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      // Calculate date range based on week offset
      const today = new Date()
      const startDate = new Date(today)
      startDate.setDate(startDate.getDate() + (weekOffset * 7))

      const endDate = new Date(startDate)
      endDate.setDate(endDate.getDate() + 13) // 2 weeks

      const params = new URLSearchParams({
        start_date: startDate.toISOString().split('T')[0],
        end_date: endDate.toISOString().split('T')[0]
      })

      if (appointmentType) {
        params.append('appointment_type', appointmentType)
      }

      // For test drives, filter by selected vehicle
      if (appointmentType === 'test_drive' && selectedVehicle) {
        params.append('inventory_id', selectedVehicle)
      }

      const res = await fetch(`${API_URL}/api/availability?${params}`)
      if (!res.ok) throw new Error('Failed to fetch availability')

      const data = await res.json()
      setAvailability(data)

      // Select first day with availability
      if (!selectedDate && data.days.length > 0) {
        const firstAvailable = data.days.find(d =>
          d.is_open && d.slots.some(s => s.is_available)
        )
        if (firstAvailable) {
          setSelectedDate(firstAvailable.date)
        }
      }
    } catch (err) {
      console.error('Error fetching availability:', err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [weekOffset, appointmentType, selectedVehicle, selectedDate])

  useEffect(() => {
    fetchAvailability()
  }, [fetchAvailability])


  // Get slots for selected date
  const selectedDayData = availability?.days.find(d => d.date === selectedDate)

  // Group slots by time for display - now includes both available AND booked slots
  const getAllSlots = () => {
    if (!selectedDayData) return []

    const slots = selectedDayData.slots

    if (!appointmentType) {
      // Group by time
      const timeMap = new Map()
      slots.forEach(slot => {
        if (!timeMap.has(slot.slot_time)) {
          timeMap.set(slot.slot_time, { available: [], booked: [] })
        }
        if (slot.is_available) {
          timeMap.get(slot.slot_time).available.push(slot)
        } else {
          timeMap.get(slot.slot_time).booked.push(slot)
        }
      })
      return Array.from(timeMap.entries())
        .map(([time, { available, booked }]) => ({
          time,
          slots: [...available, ...booked],
          isAvailable: available.length > 0,
          isBooked: booked.length > 0
        }))
        .sort((a, b) => a.time.localeCompare(b.time))
    }

    // Group by time when appointment type is specified
    const timeMap = new Map()
    slots.forEach(slot => {
      if (!timeMap.has(slot.slot_time)) {
        timeMap.set(slot.slot_time, { available: [], booked: [] })
      }
      if (slot.is_available) {
        timeMap.get(slot.slot_time).available.push(slot)
      } else {
        timeMap.get(slot.slot_time).booked.push(slot)
      }
    })

    return Array.from(timeMap.entries())
      .map(([time, { available, booked }]) => ({
        time,
        slots: available.length > 0 ? available : booked,
        isAvailable: available.length > 0,
        isBooked: booked.length > 0 && available.length === 0
      }))
      .sort((a, b) => a.time.localeCompare(b.time))
  }

  const formatTime = (time24) => {
    const [hours, minutes] = time24.split(':')
    const hour = parseInt(hours)
    const ampm = hour >= 12 ? 'PM' : 'AM'
    const hour12 = hour % 12 || 12
    return `${hour12}:${minutes} ${ampm}`
  }

  const getSelectedVehicleName = () => {
    const v = vehicles.find(v => v.id === selectedVehicle)
    return v ? v.name : 'Select Vehicle'
  }

  if (loading && !availability) {
    return (
      <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg">
        <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-accent-400 to-accent-500 rounded-xl flex items-center justify-center shadow-soft">
            <Calendar size={18} className="text-white" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-800">Availability</h2>
            <p className="text-xs text-slate-400">Available time slots</p>
          </div>
        </div>
        <div className="p-8 text-center">
          <RefreshCw size={28} className="mx-auto mb-4 animate-spin text-accent-400" />
          <p className="text-sm text-slate-500 font-medium">Loading availability...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg">
        <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-accent-400 to-accent-500 rounded-xl flex items-center justify-center shadow-soft">
            <Calendar size={18} className="text-white" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-800">Availability</h2>
            <p className="text-xs text-slate-400">Available time slots</p>
          </div>
        </div>
        <div className="p-6 text-center">
          <p className="text-sm text-error-600 mb-4">{error}</p>
          <button
            onClick={fetchAvailability}
            className="px-4 py-2 bg-white/80 border border-surface-300 rounded-xl text-sm text-slate-600 hover:border-accent-300 hover:text-accent-600 transition-all duration-200"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-accent-400 to-accent-500 rounded-xl flex items-center justify-center shadow-soft">
            <Calendar size={18} className="text-white" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-800">Availability</h2>
            <p className="text-xs text-slate-400">Available time slots</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400 bg-surface-100 px-2 py-1 rounded-md">
            {availability?.total_available || 0} slots
          </span>
          <button
            onClick={fetchAvailability}
            className="p-2 hover:bg-surface-200/50 rounded-xl transition-all duration-200"
            title="Refresh"
          >
            <RefreshCw size={14} className={`text-slate-500 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="p-5">
        {/* Vehicle Selector (for test drives or when no type specified) */}
        {(appointmentType === 'test_drive' || !appointmentType) && vehicles.length > 0 && (
          <div className="mb-5 animate-fade-in">
            <div className="text-[10px] text-slate-400 mb-2 flex items-center gap-1.5 uppercase tracking-wider font-medium">
              <Car size={12} />
              Test Drive Vehicle
            </div>
            <div className="flex flex-wrap gap-2">
              {vehicles.map((vehicle) => (
                <button
                  key={vehicle.id}
                  onClick={() => setSelectedVehicle(vehicle.id)}
                  className={`px-3 py-2.5 rounded-xl text-xs transition-all duration-200 ${
                    selectedVehicle === vehicle.id
                      ? 'bg-gradient-to-br from-accent-400 to-accent-500 text-white shadow-soft'
                      : 'bg-white/60 border border-surface-200 text-slate-600 hover:border-accent-300 hover:bg-white'
                  }`}
                >
                  <div className="font-semibold">{vehicle.year} {vehicle.make}</div>
                  <div className="text-[10px] opacity-70 mt-0.5">{vehicle.model} - {vehicle.color}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Week Navigation */}
        <div className="flex items-center justify-between mb-4">
          <button
            onClick={() => setWeekOffset(Math.max(0, weekOffset - 1))}
            disabled={weekOffset === 0}
            className="p-2 hover:bg-surface-200/50 rounded-xl disabled:opacity-30 transition-all duration-200"
          >
            <ChevronLeft size={18} className="text-slate-500" />
          </button>

          <span className="text-sm text-slate-500 font-medium">
            {availability?.start_date} to {availability?.end_date}
          </span>

          <button
            onClick={() => setWeekOffset(weekOffset + 1)}
            disabled={weekOffset >= 3}
            className="p-2 hover:bg-surface-200/50 rounded-xl disabled:opacity-30 transition-all duration-200"
          >
            <ChevronRight size={18} className="text-slate-500" />
          </button>
        </div>

        {/* Date Selector */}
        <div className="grid grid-cols-7 gap-1.5 mb-5">
          {availability?.days.slice(0, 14).map((day, i) => {
            const isSelected = day.date === selectedDate
            const hasAvailable = day.is_open && day.slots.some(s => s.is_available)
            const dayNum = new Date(day.date + 'T12:00:00').getDate()
            const dayAbbr = day.day_name.slice(0, 3)

            return (
              <button
                key={day.date}
                onClick={() => setSelectedDate(day.date)}
                disabled={!day.is_open}
                className={`p-2 rounded-xl text-center transition-all duration-200 animate-fade-in ${
                  isSelected
                    ? 'bg-gradient-to-br from-accent-400 to-accent-500 text-white shadow-soft'
                    : !day.is_open
                      ? 'bg-surface-100/50 text-slate-300 cursor-not-allowed'
                      : hasAvailable
                        ? 'bg-white/60 border border-surface-200 hover:border-accent-300 hover:bg-white text-slate-700'
                        : 'bg-surface-100/50 text-slate-400'
                }`}
                style={{ animationDelay: `${i * 0.02}s` }}
              >
                <div className="text-[10px] uppercase font-medium">{dayAbbr}</div>
                <div className="text-sm font-semibold mt-0.5">{dayNum}</div>
                {hasAvailable && !isSelected && (
                  <div className="w-1.5 h-1.5 bg-success-400 rounded-full mx-auto mt-1" />
                )}
              </button>
            )
          })}
        </div>

        {/* Time Slots */}
        {selectedDayData && (
          <div className="animate-fade-in">
            <div className="text-[10px] text-slate-400 mb-3 flex items-center gap-2 uppercase tracking-wider font-medium">
              <Clock size={12} />
              {selectedDayData.day_name}, {selectedDate}
              {selectedVehicle && appointmentType === 'test_drive' && (
                <span className="text-accent-500 ml-1 normal-case">
                  - {getSelectedVehicleName()}
                </span>
              )}
            </div>

            {!selectedDayData.is_open ? (
              <div className="text-center py-6 text-slate-400 text-sm bg-surface-100/50 rounded-xl">
                Closed on Sundays
              </div>
            ) : (
              <div className="grid grid-cols-4 gap-2 max-h-48 overflow-y-auto">
                {getAllSlots().map(({ time, slots, isAvailable, isBooked }, i) => (
                  <button
                    key={time}
                    onClick={() => isAvailable && onSlotSelect?.({
                      date: selectedDate,
                      time,
                      type: slots[0].appointment_type,
                      inventory_id: slots[0].inventory_id,
                      vehicle_name: slots[0].vehicle_name
                    })}
                    disabled={!isAvailable}
                    className={`px-2 py-2.5 rounded-xl text-xs transition-all duration-200 animate-fade-in ${
                      isAvailable
                        ? 'bg-success-50 border border-success-200 text-success-700 hover:bg-success-100 hover:border-success-300 cursor-pointer'
                        : 'bg-error-50/50 border border-error-100 text-error-400 cursor-not-allowed'
                    }`}
                    style={{ animationDelay: `${i * 0.02}s` }}
                  >
                    <span className="font-medium">{formatTime(time)}</span>
                    {isBooked && (
                      <div className="text-[10px] mt-0.5 text-error-400">Booked</div>
                    )}
                  </button>
                ))}
                {getAllSlots().length === 0 && (
                  <div className="col-span-4 text-center py-6 text-slate-400 text-sm bg-surface-100/50 rounded-xl">
                    No slots for this day
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
