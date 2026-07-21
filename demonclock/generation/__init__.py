"""The generation pipeline itself (SPEC.md §7): Director -> Story -> Quest ->
Places, running on top of the llm/ client layer (Chunk A) and writing to the
content pool that already exists (canon.py/pool.py, Step 4). Built as three
more chunks after llm/:
  - Chunk B (this one): context.py (the bounded retrieved slice every agent
    reads from) + director.py (batch intent) + pipeline.py (the orchestrator
    sim._run_batch delegates to).
  - Chunk C: story.py + quest.py, writing manifest-carrying items through
    pool.commit_or_repair.
  - Chunk D: places.py (graph extension) + wiring the AI fallback into
    resolve.py.
"""
