// Part 13 WS5 (R8): shared labels for the assessment-type UI. Lives in a
// tiny neutral module so lazy-loaded pages (BulkScore) and eager ones
// (Home, CustomerDashboard) can import the constant without pulling a
// component module into the other's chunk.
export const AI_SCORING_REQUIRES_AI_ASSESSMENT = 'AI scoring requires an AI assessment';
export const GENERIC_ROUND_TEMPLATES_NOTE =
  'Templates are AI use-case templates — generic rounds start blank';
