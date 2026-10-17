# Fase 11: fijnmazige Leonardo-provenance

## Invariant en representatie

`processed_refs` blijft coarse-grained input provenance: exact de unie van
vorige processed immutable partrevisions en de nieuwe aangeboden partrevisions.
Het is de authoritative grens van Leonardo's verwerkte input, geen lijst van
queuefiches. Een rolling state is geen primaire bron.

Fine-grained inhoudelijke provenance staat in `hypotheses[].refs`,
`uncertainties[].refs`, `open_questions[].refs`, `claims[].support` en
`claims[].counterevidence`. Deze velden mogen verwerkte partrefs en `queue:<id>`
mengen. Een queuefiche moet aantoonbaar lid zijn van minstens één concrete
immutable partrevision uit `processed_refs`. Queuebestaan of topicgelijkheid
alleen is onvoldoende. Leonardo kiest de passende granulariteit; de backend
valideert bereik en identiteit, niet de inhoudelijke waarheid van een claim.

## Onderzoek en bewijs van membership

De bestaande opslag is voldoende. Ariadne archiveert de exacte fichebytes in
`source_archive` en registreert de geordende `revision_sources`-membership bij
`part_revisions`, vóór de actieve pointer wordt gezet. Triggers blokkeren
wijziging/verwijdering van archief en revision-membership en toevoeging aan een
reeds geregistreerde actieve of historische revision. De reconstructieprimitive
verifieert bronbytes, hashes, volgorde en tokenaudit bij assignmentaanmaak en
recall. `WEEKENDKRANT-PART-1` toont de fiche-identiteiten als `SOURCE queue:<id>`.

Bij finish controleert `commit_state()` eerst de exacte processed unie tegen
de immutable assignmentsnapshot. Daarna leest het voor die specifieke
`(part_id, revision)`-paren de bestaande `revision_sources`, verbonden met
`source_archive` en `part_revisions`. Iedere itemqueue moet in die afgeleide
verzameling zitten. Ook vorige processed revisions tellen mee, niet alleen de
nieuwe parts van de huidige assignment.

Dit gebeurt deterministisch server-side onder dezelfde korte transactie en
claimfencing als statefinish. Weigering rolt jobfinish, state en receipt terug.
Er wordt geen mutable ingressqueue, actieve revisionpointer of tekstmatching
gebruikt. Geen nieuwe mappingtabel, schemamigratie of persistente kopie van de
relatie. Verwijderde redundante revisiefiles of verwijderde ingressrijen tasten
de historische bewijsrelatie niet aan.

## Contractversie en compatibiliteit

Het nieuwe outputcontract begint met `leonardo-output-v2:`. De JSON-state blijft
schema v1: velden, limieten en partrefs blijven hetzelfde. Vormvalidatie accepteert
canonieke `queue:<id>`-strings met een positief decimaal SQLite-ID (maximaal
9223372036854775807), zonder teken, voorloopnul of extra witruimte. Deze syntax
verleent op zichzelf geen membershiprecht.

De semantische finishvalidatie staat queue-itemrefs uitsluitend toe wanneer het
bevroren assignment-outputcontract die v2-marker draagt. Deploymentbestanden
worden bij finish niet gelezen. Oude assignments blijven part-only; oude
states worden niet herschreven. Nieuwe assignments bevriezen de bijgewerkte
rol- en outputtekst via de bestaande contractloader. Retries blijven de exacte
canonieke state bevestigen, ook na latere states.

`processed_refs` wordt nooit met queue-IDs uitgebreid. Gewone geldige partrefs
blijven werken. Source facts houden verplichte ondersteuning; support en
counterevidence kunnen onafhankelijk fijnmazig zijn. De 4.000-token-/32-KiB-
stategrens blijft gehandhaafd zonder truncatie of stille vergroving.

## Inspectie en recall

Volledige en compacte operatorinspectie tonen onder
`context_usage.state_provenance` de aantallen unieke itempartrefs en itemqueuerefs
(`part_ref_count`, `queue_ref_count`), of null zonder bevestigde state. Deze
metingen worden uit de immutable outputstate afgeleid, zonder extra opslag.
Ze zijn geen inhoudelijke kwaliteitsscore. De volledige inspectie bewaart de
state met alle referenties; de onderliggende membership blijft exact opvraagbaar.

De bestaande part-recall geeft de oorspronkelijke fiche-identiteiten terug.
Er is geen afzonderlijke fiche-recalltool nodig voor deze fase.

## Gerichte regressievalidatie

`tests/fast_track.txt` selecteert uitsluitend `test_leonardo_provenance`:
acceptatie van gemengde refs in alle itemvelden, onafhankelijke support en
counterevidence, exacte retries, bestaande maar onverwerkte queuefiches,
vreemde parts/revisions, malformed refs, de immutable grens na actieve revisiegroei
en ingressverwijdering, vorige processed input, weigering van zelf toegevoegde
processed refs en het oude bevroren part-only contract. De gewone partref blijft
expliciet gedekt. Dezelfde tests controleren atomaire weigering en inspectietellingen.

Ontwikkeling en PR-validatie gebruiken alleen `./start_tests.sh`. De volledige
regressiesuite wordt bewust aan de afzonderlijke CI op de exacte commit overgelaten.

Geen Kuifje, Einstein, scheduler-, deployment- of dossierherontwerp in deze fase.
