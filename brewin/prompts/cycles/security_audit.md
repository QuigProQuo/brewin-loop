## CYCLE MODE: SECURITY AUDIT
This cycle is for reviewing the codebase for security vulnerabilities.

Check for:
1. **Injection** — SQL injection, command injection, XSS, template injection.
2. **Secrets** — Hardcoded API keys, passwords, tokens in source code.
3. **Authentication/Authorization** — Missing auth checks, privilege escalation.
4. **Input validation** — Unvalidated user input, missing sanitization.
5. **Dependencies** — Known vulnerable packages (check lock files).
6. **Error handling** — Stack traces or internal details exposed to users.
7. **Data exposure** — Sensitive data in logs, responses, or error messages.

For each issue found:
- Fix it if the fix is safe and simple.
- Otherwise, log it in `.brewin/tasks.md` under `## Discovered` with severity (CRITICAL/HIGH/MEDIUM/LOW).

Do NOT refactor or add features. Security fixes only.