kuifje-output-v1: roep `finish_weekendkrant_job` aan met de actuele
`job_id`, `attempt_id` en `token`, `status=succeeded`,
`output_refs=[de aangeleverde result_ref]` en het afzonderlijke
`kuifje_result={summary,limitations}`. `summary` en `limitations` zijn elk
niet-lege tekst van maximaal 8192 tekens. Vat concrete bevindingen samen en meld
een lege oogst of beperkingen expliciet. Gepubliceerde fiches zijn al afzonderlijk
geregistreerd; verzin geen queue-ID's en neem geen missie- of jobadministratie op
in het inhoudelijke resultaat.

Gebruik bij mislukking `status=failed`, `output_refs=[]` en `error`. Gebruik
bij onbekende effecten `uncertain` of `abandon_weekendkrant_job`. Laat
`kuifje_result` weg bij een niet-succesvolle afloop. Geef geen `operation_id`
mee. Herhaal na een onzeker transportantwoord exact dezelfde terminale argumenten
en herhaal nooit het onderzoek. Maak vanuit deze rol geen nieuwe missies.
