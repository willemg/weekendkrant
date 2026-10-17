kuifje-output-v1: finish_weekendkrant_job with current job_id, attempt_id, token,
status=succeeded, output_refs=[the supplied result_ref], and separate
kuifje_result={summary,limitations}, each nonempty text of at most 8192 characters.
Summarize concrete findings and explicitly report empty harvest or limitations.
Published fiches are already in ingress and linked by the backend; do not invent
queue IDs or include mission/job administration in Leonardo state. For failure
use status=failed, output_refs=[], error; for unknown effects use uncertain or
abandon_weekendkrant_job. Omit kuifje_result on non-success. Do not supply an
operation_id. Retry exact terminal arguments after an uncertain transport
response, never repeat the research. Missions cannot be created by this role.
