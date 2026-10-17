leonardo-output-v3: state schema remains v1, with exact keys schema_version=1, dossier_id, version, previous_version, hypotheses, claims, uncertainties, open_questions, processed_refs. version is previous_version+1. hypotheses/uncertainties/open_questions are lists of {id,text,refs}; claims are {id,kind,text,support,counterevidence}, kind is source_fact or inference.

processed_refs is coarse-grained input provenance: immutable part:<id>:<revision> identifiers only. Preserve all prior processed_refs and include all supplied parts, without adding other input. Item refs, support and counterevidence are fine-grained content provenance: use a processed partref or queue:<id> for an original fiche that belongs to at least one of those exact processed immutable revisions. Both forms may be mixed. Queue existence alone is insufficient; do not use a fiche from an unprocessed revision, even the current revision of the same part. Queue identifiers are canonical positive decimal SQLite IDs, without signs or leading zeroes. Source facts require nonempty support. At most 64 items per list, 256 references per provenance list, 256 processed_refs, 4000 cl100k_base tokens, 32768 UTF-8 bytes.

Transport: call `finish_weekendkrant_job` with job_id, attempt_id and token from
the supplied claim, status and output_refs. Supply leonardo_state when returning
a dossier state. Do not supply an operation_id. For unknown effects use uncertain
or `abandon_weekendkrant_job` with the same authority and error. After an uncertain
terminal response retry only the exact terminal request, never the content work.


Separate optional finish field `kuifje_missions`: at most four proposals, each
exactly {question,rationale,scope,refs}. These are NOT state items and must never
be placed inside leonardo_state. Provide a concrete question, compact reason,
explicit research boundaries and nonempty part:/queue: refs within the validated
output state's processed corpus: prior processed revisions plus the current
assignment's immutable parts, including their archived queue members. Backend assigns mission/dossier/job identities and
stores missions as separate immutable runtime inputs atomically with this state.
Do not invent job state or spawn workers. Return [] or omit when no useful
bounded mission exists. Reevaluate with exact unchanged processed_refs order.


Optional input.research_results contains explicitly selected immutable Kuifje
outcomes (exact mission/job/attempt identity, summary/limitations or terminal
failure). This is research context, not primary source material. Never add these
outcome refs to processed_refs or item source refs; those remain part:/queue:
only. Evaluate findings and limitations editorially in normal compact state,
without embedding mission objects, result objects or their administration.
