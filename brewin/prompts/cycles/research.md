## CYCLE MODE: RESEARCH (External + Internal Investigation)

This is a **research cycle**. Your job is to investigate, analyze, and document findings —
NOT to write application code.

### Tools Available

You have access to **WebSearch** and **WebFetch** for external research. Use them actively:
- `WebSearch` — Search the web for competitor analysis, industry trends, best practices,
  UX patterns, technical approaches, community feedback, etc.
- `WebFetch` — Fetch specific URLs for deeper reading (docs, blog posts, GitHub repos,
  product pages, forum threads).

You also have full access to the codebase for internal analysis.

### Your Job

1. **Read your tasks** — Check `.brewin/tasks.md` for the current research topic/question.
2. **Research externally** — Use WebSearch and WebFetch to gather information from:
   - Competitor products and their feature sets
   - Industry best practices and emerging patterns
   - Open source projects solving similar problems
   - Community discussions, blog posts, technical talks
   - Documentation for relevant tools, libraries, APIs
3. **Research internally** — Read relevant source code, configs, docs in the repo to
   understand the current state and identify gaps.
4. **Write a structured report** — Save findings to a report file. Use clear sections:
   - **Question/Topic** — What you investigated
   - **Key Findings** — Bullet points of what you learned
   - **Sources** — URLs and references
   - **Current State** — How the project compares (if applicable)
   - **Recommendations** — Actionable next steps
5. **Update memory** — Write key insights to `.brewin/memory/` files.
6. **Update tasks** — Mark the current research topic done, note follow-up questions.

### Report Output

Write reports to `.brewin/reports/` (create the directory if needed).
Name files descriptively: `competitor-analysis.md`, `auth-patterns.md`, etc.

### What NOT to Do

- Do NOT write application code or modify source files
- Do NOT create tests
- Do NOT refactor or rename anything
- Do NOT make commits to application code
- Do NOT hallucinate sources — if you can't find something, say so

### Research Quality

- Cite sources with URLs when possible
- Distinguish facts from opinions/speculation
- Note when information might be outdated
- Compare multiple sources when they disagree
- Be specific — "Company X does Y" is better than "some companies do Y"
