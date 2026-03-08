## CYCLE MODE: DEBUG
This cycle is for systematic bug investigation and fixing.

Follow this structured approach:
1. REPRODUCE — Confirm the bug exists. Write a failing test if possible.
2. HYPOTHESIZE — Form a theory about the root cause based on symptoms.
3. ISOLATE — Narrow down the cause. Add logging, check assumptions, trace the code path.
4. ROOT CAUSE — Identify the exact line(s) causing the issue.
5. FIX — Make the minimal change to fix the root cause.
6. VERIFY — Run tests, confirm the fix, check for side effects.
7. PREVENT — Add a regression test if one doesn't exist.

Do NOT guess-and-check. Be methodical. Document your findings in the commit message.