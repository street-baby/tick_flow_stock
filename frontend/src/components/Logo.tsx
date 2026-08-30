import React from 'react'

interface LogoProps {
  className?: string
  size?: number
  style?: React.CSSProperties
  variant?: 'emblem' | 'full'
}

export function Logo({ className, size = 32, style, variant = 'emblem' }: LogoProps) {
  if (variant === 'full') {
    return (
      <img
        src="/brand/logo_crop.png"
        alt="云之心量化 CLOUD HEART QUANT"
        className={className}
        style={{ height: size, width: 'auto', objectFit: 'contain', ...style }}
      />
    )
  }

  return (
    <div
      className={`relative inline-flex items-center justify-center shrink-0 ${className || ''}`}
      style={{ width: size, height: size, ...style }}
    >
      <img
        src="/brand/logo_emblem.png"
        alt="云之心量化"
        className="w-full h-full object-contain drop-shadow-[0_0_12px_rgba(56,189,248,0.45)] rounded-md"
      />
    </div>
  )
}
