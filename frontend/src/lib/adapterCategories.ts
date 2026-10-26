/** The order the categories of the services come in, in the library and wherever a list of services is grouped alike. */
export const CATEGORY_ORDER = ['basics', 'feeds', 'generic', 'hosts', 'nas', 'downloads', 'media', 'network', 'monitoring', 'other']

/** Position of a category in the shared order; one nobody knows goes last. */
export function categoryRank(category: string): number {
  const at = CATEGORY_ORDER.indexOf(category)
  return at === -1 ? CATEGORY_ORDER.length : at
}
