## CYCLE MODE: EXPLORE (Codebase Discovery)

This is a **codebase exploration** cycle. Your job is to READ and UNDERSTAND,
not to write code.

### Your Job:
1. Read the project tree and identify the key directories and their purposes.
2. Open and read the 5-10 most important files: entry points, main modules,
   config files, core data models.
3. Trace one critical path end-to-end (e.g., HTTP request → handler → DB).
4. Identify: architecture patterns, frameworks/libraries in use, testing
   approach, build system, deployment setup.
5. Write your findings to `.brewin/memory/architecture.md`:
   - Key files and what they do (one line each)
   - Architecture pattern (MVC, hexagonal, monolith, etc.)
   - Data flow for the main use case
   - Testing approach and framework
   - Build/deploy commands
   - Key dependencies and their roles

### What NOT to do:
- Do NOT write any application code
- Do NOT create tests
- Do NOT refactor or rename anything
- Do NOT modify any source files

### Output:
Your cycle summary should describe the architecture you discovered.
The real deliverable is a populated `memory/architecture.md`.
