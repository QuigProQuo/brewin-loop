## CYCLE MODE: TEST WRITING
This cycle is dedicated to improving test coverage. Do NOT write application/feature code.

Your job:
1. Read existing tests to understand current coverage and patterns.
2. Identify gaps: untested functions, missing edge cases, error paths.
3. Write tests following the project's existing test conventions.
4. Run the full test suite to verify all tests pass (old and new).
5. Commit the new tests.

Focus on high-value coverage: critical paths, complex logic, and recently changed code.
Prefer fewer thorough tests over many shallow ones.

### Scope:
Write tests ONLY for code that was recently changed or is currently untested on
critical paths. Do NOT aim for 100% coverage. Do NOT write tests for trivial
getters/setters, configuration, or boilerplate. Focus on: complex logic, error
handling, and integration points. Limit yourself to 3-5 high-value test cases
per cycle.