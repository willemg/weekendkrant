"""Frozen WEEKENDKRANT-PART-1 serialization, part of durable provenance.

Never alter this renderer to evolve the current format. A new format requires
explicit version dispatch/migration before its files may be retired.
"""

TOKENIZER = 'cl100k_base'


def render(items, week, topic, part, revision, reserve):
    head = (f'WEEKENDKRANT-PART-1\nweek: {week}\ntopic: {topic}\npart: {part}\n'
            f'revision: {revision}\ntokenizer: {TOKENIZER}\nreserved_tokens: {reserve}\n\n')
    return head + ''.join(
        f'\n--- SOURCE {f.path} date={f.date} sha256={f.sha256} bytes={len(f.data)} ---\n'
        + f.data.decode('utf-8') + '\n--- END SOURCE ---\n' for f in items)

