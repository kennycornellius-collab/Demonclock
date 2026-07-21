"""Provider-agnostic LLM client layer (SPEC.md §1/§7, Step 5 Chunk A).

SPEC.md §1 originally resolved on a single Anthropic-only generation engine;
that decision was deliberately reopened at the user's request so different
generation roles (Director/Story/Quest/Places/entity-resolution) can use
whichever LLM suits them, and so a role can fail over to a second provider
rather than a single vendor outage stalling the whole batch. The provider-
independent requirements from the original decision carry over unchanged:
every call declares a JSON schema up front (never "please reply in JSON"
prose prompting) and malformed output gets exactly one retry before the item
is discarded.

Two failure modes (errors.py) map to the two things that can go wrong:
  - LLMProviderError: the provider/transport itself failed (network, auth,
    5xx). Recoverable by trying the NEXT provider in a role's chain.
  - MalformedGenerationError: the provider answered, but its output isn't
    valid against the requested schema even after one retry. NOT a fallback
    trigger -- a different provider would face the same "the caller's prompt
    produced bad output" problem, so this bubbles up to the caller to
    discard the item (SPEC.md §1/§8: the pool absorbs the loss).

Only Gemini (providers/gemini.py) and a deterministic offline `mock`
(providers/mock.py, used by every test and by real play when no key is
configured) ship in this chunk. Adding Anthropic or OpenAI later is exactly
one new file in `llm/providers/` implementing `LLMClient` plus one line in
`registry.PROVIDER_CLASSES` -- nothing else in this package (or any caller)
needs to change.
"""
