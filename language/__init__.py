"""
LANGUAGE package — human-language intelligence.

    normalizer.py      lowercase/unaccent/lemmatize-lite → preprocess
    spell_corrector.py SymSpell-style dictionary correction, context-guarded
    entity_resolver.py BLINK-style entity registry + mention→candidate ranking
    semantic_parser.py surface-text → semantic-meaning understanding
    context_resolver.py pronoun/reference resolution + situation awareness

Pipeline (runs BEFORE intent resolution when needed):

    RAW INPUT → normalizer → spell corrector (guarded) → entity resolver
             → semantic parser → intent classifier → action

The design is model-agnostic and local-first: everything runs deterministically
offline and only falls back to the LLM for genuinely ambiguous cases.
"""
