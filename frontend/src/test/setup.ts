import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'

// ⚠️ Four seconds for findBy and waitFor, not Testing Library's one. With the
// whole suite running beside other work the library of 165 integrations took
// longer than a second to show its buttons, and the run went red on
// WidgetLibraryOptional with "Unable to find role=button" on 08.10.2026,
// green three times alone. A missing element still fails, just later.
configure({ asyncUtilTimeout: 4000 })

// Components read their texts through i18next; the English bundle makes
// accessible names such as "Refresh now" available to the tests.
import '../i18n'
