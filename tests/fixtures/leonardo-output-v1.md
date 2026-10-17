leonardo-state-v1: exact keys schema_version=1, dossier_id, version, previous_version, hypotheses, claims, uncertainties, open_questions, processed_refs. version is previous_version+1. hypotheses/uncertainties/open_questions are lists of {id,text,refs}; claims are {id,kind,text,support,counterevidence}, kind is source_fact or inference. References are supplied part:<id>:<revision> identifiers. Preserve all prior processed_refs and include all supplied parts. At most 64 items per list, 256 processed_refs, 4000 cl100k_base tokens, 32768 UTF-8 bytes.

Transport: call `finish_weekendkrant_job` with job_id, attempt_id and token from
the supplied claim, status and output_refs. Supply leonardo_state when returning
a dossier state. Do not supply an operation_id. For unknown effects use uncertain
or `abandon_weekendkrant_job` with the same authority and error. After an uncertain
terminal response retry only the exact terminal request, never the content work.
