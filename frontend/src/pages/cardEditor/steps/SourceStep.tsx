import { StepFrame } from './StepFrame'

/**
 * Step 1, Source (KARTEN-9 AC-3, EC-1, EC-2, EC-4, EC-9): the kind of connection, the connection to probe with, the
 * requests with their paths and how often they are made, the probe and its answer as a tree, and "Use this answer
 * as demo data" (AC-10). Fields read and write the card through `useCardField`.
 */
export function SourceStep() {
  return <StepFrame step="source" />
}
