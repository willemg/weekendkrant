leonardo-output-v3: het stateschema blijft v1, met exact de sleutels
schema_version=1, dossier_id, version, previous_version, hypotheses, claims,
uncertainties, open_questions, processed_refs. `version` is
`previous_version+1`. `hypotheses`, `uncertainties` en `open_questions`
zijn lijsten van {id,text,refs}; `claims` zijn
{id,kind,text,support,counterevidence}, waarbij `kind` `source_fact` of
`inference` is.

`processed_refs` is grofmazige inputprovenance: uitsluitend immutable
`part:<id>:<revision>`-identifiers. Behoud alle eerdere `processed_refs` en
neem alle aangeleverde parts op, zonder andere input toe te voegen. Item-`refs`,
`support` en `counterevidence` zijn fijnmazige inhoudsprovenance: gebruik een
verwerkte partref of `queue:<id>` voor een oorspronkelijke fiche die tot minstens
één van precies die verwerkte immutable revisies behoort. Beide vormen mogen
gemengd worden. Het bestaan van een queue-ID alleen volstaat niet; gebruik geen
fiche uit een onverwerkte revisie, ook niet uit de huidige revisie van dezelfde
part. Queue-identifiers zijn canonieke positieve decimale SQLite-ID's, zonder
teken of voorloopnullen. Voor `source_fact` moet `support` niet leeg zijn.
Gebruik maximaal 64 items per lijst, 256 references per provenancelijst,
256 `processed_refs`, 4000 `cl100k_base`-tokens en 32768 UTF-8-bytes.

Transport: roep `finish_weekendkrant_job` aan met `job_id`, `attempt_id` en
`token` uit de aangeleverde claim, plus `status` en `output_refs`. Geef
`leonardo_state` mee wanneer je een dossierstate terugstuurt. Geef geen
`operation_id` mee. Gebruik bij onbekende effecten `uncertain` of
`abandon_weekendkrant_job` met dezelfde autoriteit en een foutmelding. Na een
onzeker terminaal antwoord mag alleen exact hetzelfde terminale request opnieuw
worden geprobeerd, nooit het inhoudelijke werk.

Het afzonderlijke optionele finishveld `kuifje_missions` bevat maximaal vier
voorstellen, elk exact {question,rationale,scope,refs}. Dit zijn geen state-items
en ze mogen nooit in `leonardo_state` worden geplaatst. Geef een concrete vraag,
een compacte reden, expliciete onderzoeksgrenzen en niet-lege `part:`/`queue:`
refs binnen het verwerkte corpus van de geldige outputstate: eerdere verwerkte
revisies plus de immutable parts uit de huidige assignment, inclusief hun
gearchiveerde queueleden. Verzin geen jobstate en start geen workers. Geef `[]`
terug of laat het veld weg wanneer er geen nuttige begrensde missie is. Bij
reevaluation blijft de volgorde van `processed_refs` exact ongewijzigd.

Het optionele `input.research_results` bevat expliciet geselecteerde immutable
onderzoeksresultaten, met exacte missie-, job- en attemptidentiteit en een
samenvatting en beperkingen of een terminale mislukking. Dit is onderzoekscontext,
geen primair bronmateriaal. Voeg refs van deze resultaten nooit toe aan
`processed_refs` of item-bronrefs; die blijven uitsluitend `part:`/`queue:`.
Beoordeel bevindingen en beperkingen redactioneel in de normale compacte state,
zonder missieobjecten, resultaatobjecten of operationele administratie in de state
op te nemen.
