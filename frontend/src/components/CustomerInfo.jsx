import React from 'react'
import { User, Phone, Mail, Car } from 'lucide-react'

export default function CustomerInfo({ customer }) {
  if (!customer || !customer.customer_id) {
    return (
      <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg">
        <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-soft-400 to-soft-500 rounded-xl flex items-center justify-center shadow-soft">
            <User size={18} className="text-white" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-800">Customer</h2>
            <p className="text-xs text-slate-400">Caller information</p>
          </div>
        </div>
        <div className="p-8 text-center">
          <div className="w-16 h-16 mx-auto mb-4 bg-surface-200/50 rounded-2xl flex items-center justify-center">
            <User size={28} className="text-slate-300" />
          </div>
          <p className="text-sm text-slate-500 font-medium">Not identified yet</p>
          <p className="text-xs text-slate-400 mt-1">Waiting for phone number...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="glass-card rounded-3xl overflow-hidden shadow-glass-lg animate-fade-in-scale">
      <div className="px-5 py-4 bg-gradient-to-r from-white/80 to-surface-100/80 border-b border-surface-200/50 flex items-center gap-3">
        <div className="w-10 h-10 bg-gradient-to-br from-soft-400 to-soft-500 rounded-xl flex items-center justify-center shadow-soft">
          <User size={18} className="text-white" />
        </div>
        <div>
          <h2 className="font-semibold text-slate-800">Customer</h2>
          <p className="text-xs text-slate-400">Caller information</p>
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Avatar & Name */}
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 bg-gradient-to-br from-accent-400 to-soft-500 rounded-2xl flex items-center justify-center text-xl font-bold text-white shadow-soft">
            {customer.name ? customer.name.charAt(0).toUpperCase() : '?'}
          </div>
          <div>
            <div className="font-semibold text-slate-800 text-lg">{customer.name || 'Unknown'}</div>
            <div className="text-xs text-slate-400 font-mono bg-surface-100 px-2 py-0.5 rounded-md inline-block mt-1">
              ID: {customer.customer_id}
            </div>
          </div>
        </div>

        {/* Contact Info */}
        <div className="space-y-2 pt-3 border-t border-surface-200">
          {customer.phone && (
            <div className="flex items-center gap-3 text-sm bg-white/60 backdrop-blur-sm px-4 py-3 rounded-xl border border-surface-200 transition-all duration-200 hover:border-soft-300 hover:shadow-sm">
              <div className="w-8 h-8 bg-soft-100 rounded-lg flex items-center justify-center">
                <Phone size={14} className="text-soft-500" />
              </div>
              <span className="text-slate-700 font-medium">{customer.phone}</span>
            </div>
          )}
          {customer.email && (
            <div className="flex items-center gap-3 text-sm bg-white/60 backdrop-blur-sm px-4 py-3 rounded-xl border border-surface-200 transition-all duration-200 hover:border-accent-300 hover:shadow-sm">
              <div className="w-8 h-8 bg-accent-100 rounded-lg flex items-center justify-center">
                <Mail size={14} className="text-accent-500" />
              </div>
              <span className="text-slate-700 font-medium">{customer.email}</span>
            </div>
          )}
        </div>

        {/* Vehicles */}
        {customer.vehicles && customer.vehicles.length > 0 && (
          <div className="pt-3 border-t border-surface-200">
            <div className="text-[10px] text-slate-400 mb-3 uppercase tracking-wider font-medium">Vehicles</div>
            <div className="space-y-2">
              {customer.vehicles.map((v, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 text-sm bg-white/60 backdrop-blur-sm px-4 py-3 rounded-xl border border-surface-200 transition-all duration-200 hover:border-success-300 hover:shadow-sm animate-fade-in"
                  style={{ animationDelay: `${i * 0.1}s` }}
                >
                  <div className="w-8 h-8 bg-success-100 rounded-lg flex items-center justify-center">
                    <Car size={14} className="text-success-500" />
                  </div>
                  <span className="text-slate-700 font-medium">{v.year} {v.make} {v.model}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
