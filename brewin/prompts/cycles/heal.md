## CYCLE MODE: HEAL (Fix Broken Baseline)
The project's build or tests are ALREADY FAILING before you start.
Your ONLY job is to get the project back to a healthy state.

1. Read the health check output below carefully.
2. Diagnose why the build/tests are failing.
3. If the failure is a CONFIG PROBLEM (wrong file paths, wrong project names, wrong scheme names in `.brewin/config.toml`), fix the config file. For example, if the build command references a `.xcodeproj` or scheme that doesn't exist, find the correct project file and update `.brewin/config.toml` accordingly.
4. If the failure is a CODE PROBLEM, fix it with minimal, targeted changes.
5. Run the build/tests yourself to verify they pass.
6. Commit the fix.

The health check commands are defined in `.brewin/config.toml` under `[health]`. You CAN and SHOULD edit this file if the commands are wrong.

Do NOT start feature work. Do NOT refactor. Just heal the project.