"""Ariadne's canonical deterministic context measure, never provider usage.

cl100k_base is the current audit vocabulary, not a claim about model billing.
Changing it requires explicit versioned runtime audit metadata. Historical
WEEKENDKRANT-PART-1 audit remains self-contained in part_format_v1.py.
"""
TOKENIZER = 'cl100k_base'


def token_count(text):
    import tiktoken
    return len(tiktoken.get_encoding(TOKENIZER).encode(text, disallowed_special=()))


def measure(text):
    return dict(bytes=len(text.encode('utf-8')), tokens=token_count(text), tokenizer=TOKENIZER)
