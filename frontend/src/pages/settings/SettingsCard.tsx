import type { ReactNode } from 'react'

/** One block on a settings page: heading, a line of explanation, the controls. */
export function SettingsCard({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <div className="glass rounded-2xl p-5 mb-4">
      <h2 className="font-semibold text-[15px]">{title}</h2>
      {description && <p className="text-sm text-muted mt-0.5 mb-3">{description}</p>}
      {!description && <div className="mb-3" />}
      {children}
    </div>
  )
}
