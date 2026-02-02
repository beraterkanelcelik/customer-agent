import React from 'react'
import { User, Phone, Mail, Car } from 'lucide-react'

export default function CustomerInfo({ customer }) {
  if (!customer || !customer.customer_id) {
    return (
      <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
          <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-cyan-600 rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/20">
            <User size={16} className="text-white" />
          </div>
          <h2 className="font-semibold text-white">Customer</h2>
        </div>
        <div className="p-5 text-center text-gray-500 py-8">
          <User size={28} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">Not identified yet</p>
          <p className="text-xs mt-1 text-gray-600">Waiting for phone number...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900/50 backdrop-blur border border-gray-800/50 rounded-2xl overflow-hidden shadow-xl">
      <div className="px-5 py-4 bg-gradient-to-r from-gray-800/50 to-gray-800/30 border-b border-gray-700/50 flex items-center gap-2">
        <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-cyan-600 rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/20">
          <User size={16} className="text-white" />
        </div>
        <h2 className="font-semibold text-white">Customer</h2>
      </div>

      <div className="p-5 space-y-4">
        {/* Avatar & Name */}
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center text-lg font-bold shadow-lg shadow-indigo-500/30">
            {customer.name ? customer.name.charAt(0).toUpperCase() : '?'}
          </div>
          <div>
            <div className="font-medium text-white">{customer.name || 'Unknown'}</div>
            <div className="text-xs text-gray-400">ID: {customer.customer_id}</div>
          </div>
        </div>

        {/* Contact Info */}
        <div className="space-y-2 pt-3 border-t border-gray-800/50">
          {customer.phone && (
            <div className="flex items-center gap-2 text-sm bg-gray-800/30 px-3 py-2 rounded-lg">
              <Phone size={14} className="text-blue-400" />
              <span>{customer.phone}</span>
            </div>
          )}
          {customer.email && (
            <div className="flex items-center gap-2 text-sm bg-gray-800/30 px-3 py-2 rounded-lg">
              <Mail size={14} className="text-purple-400" />
              <span>{customer.email}</span>
            </div>
          )}
        </div>

        {/* Vehicles */}
        {customer.vehicles && customer.vehicles.length > 0 && (
          <div className="pt-3 border-t border-gray-800/50">
            <div className="text-xs text-gray-400 mb-2 uppercase tracking-wide">Vehicles</div>
            {customer.vehicles.map((v, i) => (
              <div key={i} className="flex items-center gap-2 text-sm bg-gray-800/30 px-3 py-2 rounded-lg">
                <Car size={14} className="text-cyan-400" />
                <span>{v.year} {v.make} {v.model}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
