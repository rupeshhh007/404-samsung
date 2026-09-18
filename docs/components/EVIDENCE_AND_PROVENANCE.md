# Evidence and Provenance

Evidence records source observations (`FRAME`, `AUDIO`, `USER`, `TOOL`, `SYSTEM`) and derived interpretations separately. A frame content hash/reference is immutable; “E14 observed in FRAME-21” is derived evidence pointing to the frame. Contradictory E17 interpretation adds a record and contradiction edge, never rewrites FRAME-21.

Temporal resolution receives ordered metadata and returns candidate IDs. “the code before this one” can anchor FRAME-21 instead of FRAME-38; low confidence clarifies. Tool results record provider request/effect IDs and authority semantics. `expires_at` makes evidence stale for claims but does not delete provenance.

Raw media is referenced, access-limited, and not placed in logs; demo reset clears memory. Retention defaults to session retention. Tests: T-EVD-01 and T-REF-01.
