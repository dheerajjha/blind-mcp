# Level classification semantics

`classify` is a title heuristic. Explicit markers such as `senior`, `staff`,
and `intern` select a level; an unmarked title currently falls into the `mid`
bucket for compatibility with the existing report shape. Callers should keep
the original title and treat that default as an inferred value, not evidence
that the employer advertised a mid-level role.
