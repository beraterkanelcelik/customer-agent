import React from 'react'
import { User, Phone, Mail, Car } from 'lucide-react'

export default function CustomerInfo({ customer }) {
  if (!customer || !customer.customer_id) {
    return (
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
          <User size={18} className="text-blue-400" />
          <h2 className="font-semibold">Customer</h2>
        </div>
        <div className="p-4 text-center text-gray-500 py-6">
          <User size={24} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">Not identified yet</p>
          <p className="text-xs mt-1">Waiting for phone number...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <User size={18} className="text-blue-400" />
        <h2 className="font-semibold">Customer</h2>
      </div>

      <div className="p-4 space-y-3">
        {/* Avatar & Name */}
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-indigo-600 rounded-full flex items-center justify-center text-lg font-bold">
            {customer.name ? customer.name.charAt(0).toUpperCase() : '?'}
          </div>
          <div>
            <div className="font-medium">{customer.name || 'Unknown'}</div>
            <div className="text-xs text-gray-400">ID: {customer.customer_id}</div>
          </div>
        </div>

        {/* Contact Info */}
        <div className="space-y-2 pt-2 border-t border-gray-800">
          {customer.phone && (
            <div className="flex items-center gap-2 text-sm">
              <Phone size={14} className="text-gray-500" />
              <span>{customer.phone}</span>
            </div>
          )}
          {customer.email && (
            <div className="flex items-center gap-2 text-sm">
              <Mail size={14} className="text-gray-500" />
              <span>{customer.email}</span>
            </div>
          )}
        </div>

        {/* Vehicles */}
        {customer.vehicles && customer.vehicles.length > 0 && (
          <div className="pt-2 border-t border-gray-800">
            <div className="text-xs text-gray-400 mb-2">Vehicles</div>
            {customer.vehicles.map((v, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <Car size={14} className="text-gray-500" />
                <span>{v.year} {v.make} {v.model}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
