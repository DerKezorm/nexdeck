import type { ReactNode } from 'react'

/** One block on a settings page: heading, a line of explanation, the controls; ``action`` stands beside the heading. */
export function SettingsCard({ title, description, children, action }: { title: string; description?: string; children: ReactNode; action?: ReactNode }) {
  const head = (
    <>
      <h2 className="font-semibold text-[15px]">{title}</h2>
      {description && <p className="text-sm text-muted mt-0.5 mb-3">{description}</p>}
      {!description && <div className="mb-3" />}
    </>
  )
  return (
    <div className="glass rounded-2xl p-5 mb-4">
      {action ? (
        // On a phone the button goes under the words, across the whole card.
        <div className="flex flex-wrap items-start gap-x-4">
          <div className="flex-[1_1_260px] min-w-0">{head}</div>
          <div className="max-md:w-full max-md:mb-3 max-md:[&>.btn]:w-full">{action}</div>
        </div>
      ) : (
        head
      )}
      {children}
    </div>
  )
}
