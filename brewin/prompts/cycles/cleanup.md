## CYCLE MODE: CLEANUP
This cycle is for mechanical code hygiene. No behavior changes.

Your job:
1. Remove dead code (unused functions, unreachable branches, commented-out code).
2. Fix lint warnings and formatting issues.
3. Clean up imports (remove unused, sort/organize).
4. Update outdated dependencies if safe (patch/minor versions only).
5. Remove temporary files, debug artifacts, stale TODOs.
6. Run the test suite to verify nothing broke.
7. Commit.

Do NOT refactor architecture. Do NOT add features. Do NOT fix bugs (log them instead). Keep changes purely mechanical.