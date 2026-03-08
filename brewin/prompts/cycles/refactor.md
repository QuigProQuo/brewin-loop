## CYCLE MODE: REFACTOR
This cycle is for behavior-preserving code restructuring ONLY.

Your job:
1. Run the test suite FIRST to establish a passing baseline.
2. Make structural improvements: extract functions, rename for clarity, reduce duplication, simplify complex logic.
3. Run the test suite AFTER each significant change.
4. If tests break, revert that change and try a smaller scope.
5. Commit when tests pass.

Do NOT add features. Do NOT change behavior. Do NOT fix bugs (log them in .brewin/tasks.md instead). The test suite is your proof that behavior is preserved.