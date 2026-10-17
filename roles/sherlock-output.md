# Outputcontract voor Sherlock

Dit outputcontract hoort bij de rol Sherlock.

De exacte resultaatreferentie wordt als `result_ref` aangeleverd. Geef bij
`finish_weekendkrant_job` uitsluitend die referentie mee als `output_refs`,
ook bij een lege oogst. Claimgegevens zijn transportmetadata, geen fiche-inhoud.

`succeeded` vereist inhoudelijk voltooide zoekdekking, registratie van alle
werkelijk gereviewde bronnen en bevestiging van alle geselecteerde fiches.
`failed` sluit een bekend mislukte uitvoering af. Gebruik bij onzekere effecten
`uncertain` of `abandon_weekendkrant_job`.

Transport: roep `finish_weekendkrant_job` aan met `job_id`, `attempt_id` en
`token` uit de aangeleverde claim, plus `status` en `output_refs`. Geef geen
`operation_id` mee. Gebruik bij onbekende effecten `uncertain` of
`abandon_weekendkrant_job` met dezelfde autoriteit en een foutmelding. Na een
onzeker terminaal antwoord mag alleen exact hetzelfde terminale verzoek opnieuw
worden geprobeerd, nooit het inhoudelijke werk.
