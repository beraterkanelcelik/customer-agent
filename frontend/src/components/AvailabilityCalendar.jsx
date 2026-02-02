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
      <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-br from-cyan-500 to-teal-600 rounded-lg flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <Calendar size={16} className="text-white" />
          </div>
          <h2 className="font-semibold text-white">Availability</h2>
        </div>
        <div className="p-8 text-center">
          <RefreshCw size={28} className="mx-auto mb-3 animate-spin text-gray-500" />
          <p className="text-sm text-gray-500">Loading availability...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-br from-cyan-500 to-teal-600 rounded-lg flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <Calendar size={16} className="text-white" />
          </div>
          <h2 className="font-semibold text-white">Availability</h2>
        </div>
        <div className="p-5 text-center text-red-400">
          <p className="text-sm">{error}</p>
          <button
            onClick={fetchAvailability}
            className="mt-3 px-4 py-2 bg-gray-800 rounded-lg text-xs hover:bg-gray-700 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-br from-cyan-500 to-teal-600 rounded-lg flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <Calendar size={16} className="text-white" />
          </div>
          <h2 className="font-semibold text-white">Availability</h2>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            {availability?.total_available || 0} slots
          </span>
          <button
            onClick={fetchAvailability}
            className="p-1.5 hover:bg-gray-700 rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="p-5">
        {/* Vehicle Selector (for test drives or when no type specified) */}
        {(appointmentType === 'test_drive' || !appointmentType) && vehicles.length > 0 && (
          <div className="mb-4">
            <div className="text-xs text-gray-400 mb-2 flex items-center gap-1.5">
              <Car size={12} />
              Test Drive Vehicle
            </div>
            <div className="flex flex-wrap gap-2">
              {vehicles.map((vehicle) => (
                <button
                  key={vehicle.id}
                  onClick={() => setSelectedVehicle(vehicle.id)}
                  className={`px-3 py-2 rounded-lg text-xs transition-all ${
                    selectedVehicle === vehicle.id
                      ? 'bg-gradient-to-br from-cyan-500 to-teal-600 text-white shadow-lg shadow-cyan-500/20'
                      : 'bg-gray-800/50 text-gray-300 hover:bg-gray-800'
                  }`}
                >
                  <div className="font-medium">{vehicle.year} {vehicle.make}</div>
                  <div className="text-[10px] opacity-70">{vehicle.model} - {vehicle.color}</div>
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
            className="p-1.5 hover:bg-gray-800 rounded-lg disabled:opacity-30 transition-colors"
          >
            <ChevronLeft size={18} />
          </button>

          <span className="text-sm text-gray-400">
            {availability?.start_date} to {availability?.end_date}
          </span>

          <button
            onClick={() => setWeekOffset(weekOffset + 1)}
            disabled={weekOffset >= 3}
            className="p-1.5 hover:bg-gray-800 rounded-lg disabled:opacity-30 transition-colors"
          >
            <ChevronRight size={18} />
          </button>
        </div>

        {/* Date Selector */}
        <div className="grid grid-cols-7 gap-1.5 mb-4">
          {availability?.days.slice(0, 14).map((day) => {
            const isSelected = day.date === selectedDate
            const hasAvailable = day.is_open && day.slots.some(s => s.is_available)
            const dayNum = new Date(day.date + 'T12:00:00').getDate()
            const dayAbbr = day.day_name.slice(0, 3)

            return (
              <button
                key={day.date}
                onClick={() => setSelectedDate(day.date)}
                disabled={!day.is_open}
                className={`p-2 rounded-lg text-center transition-all ${
                  isSelected
                    ? 'bg-gradient-to-br from-cyan-500 to-teal-600 text-white shadow-lg shadow-cyan-500/20'
                    : !day.is_open
                      ? 'bg-gray-800/30 text-gray-600 cursor-not-allowed'
                      : hasAvailable
                        ? 'bg-gray-800/50 hover:bg-gray-800 text-white'
                        : 'bg-gray-800/30 text-gray-500'
                }`}
              >
                <div className="text-[10px] uppercase">{dayAbbr}</div>
                <div className="text-sm font-medium">{dayNum}</div>
                {hasAvailable && !isSelected && (
                  <div className="w-1.5 h-1.5 bg-green-400 rounded-full mx-auto mt-1 shadow-lg shadow-green-400/50" />
                )}
              </button>
            )
          })}
        </div>

        {/* Time Slots */}
        {selectedDayData && (
          <div>
            <div className="text-xs text-gray-400 mb-3 flex items-center gap-1.5">
              <Clock size={12} />
              {selectedDayData.day_name}, {selectedDate}
              {selectedVehicle && appointmentType === 'test_drive' && (
                <span className="text-cyan-400 ml-2">
                  - {getSelectedVehicleName()}
                </span>
              )}
            </div>

            {!selectedDayData.is_open ? (
              <div className="text-center py-4 text-gray-500 text-sm">
                Closed on Sundays
              </div>
            ) : (
              <div className="grid grid-cols-4 gap-2 max-h-48 overflow-y-auto">
                {getAllSlots().map(({ time, slots, isAvailable, isBooked }) => (
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
                    className={`px-2 py-2 rounded-lg text-xs transition-all ${
                      isAvailable
                        ? 'bg-green-900/20 border border-green-700/30 text-green-300 hover:bg-green-800/30 hover:border-green-600/50 cursor-pointer'
                        : 'bg-red-900/30 border border-red-700/40 text-red-400 cursor-not-allowed opacity-70'
                    }`}
                  >
                    <span>{formatTime(time)}</span>
                    {isBooked && (
                      <div className="text-[10px] mt-0.5 text-red-500">Booked</div>
                    )}
                  </button>
                ))}
                {getAllSlots().length === 0 && (
                  <div className="col-span-4 text-center py-4 text-gray-500 text-sm">
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
