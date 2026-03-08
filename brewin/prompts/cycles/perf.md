## CYCLE MODE: PERFORMANCE
This cycle is for profiling and optimizing performance.

Rules:
- MEASURE before optimizing. Never guess at bottlenecks.
- BENCHMARK before and after changes to prove improvement.
- DOCUMENT what you measured and what improved in the commit message.

Your job:
1. Identify the hot path or performance concern.
2. Profile or benchmark the current state.
3. Optimize: algorithm improvements, caching, reducing allocations, batching I/O, eliminating redundant work.
4. Benchmark again to verify improvement.
5. Run the test suite to ensure correctness.
6. Commit with before/after metrics in the commit message.

Do NOT sacrifice readability for micro-optimizations. Focus on algorithmic wins and eliminating waste.