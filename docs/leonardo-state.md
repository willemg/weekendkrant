# Leonardo-state v1, fase-8-slice

Deze slice implementeert expliciete dossier- en jobaanmaak in de Python-backend,
ready-dispatch via de bestaande dispatcher en statefinish via de bestaande
HTTP/MCP-tool. Geen permanente worker, nieuwe scheduler, automatische
jobproductie uit offers, model-API-call, missie-uitvoering of fase-9-proefcyclus.
Een topic is geen dossier: de aanroeper kiest expliciet een inhoudelijke
`dossier_id`. De eerste slice begrenst een dossier tot één topic.

## Opslag en identiteit

Schema 11 voegt vier append-only tabellen toe: `leonardo_dossiers`,
`leonardo_assignments`, `leonardo_assignment_parts`, `leonardo_states`.
Update, delete en replace worden door triggers geweigerd. Bestaande data krijgt
geen automatische dossierindeling. De huidige state is de hoogste opgeslagen
versie van het dossier; er bestaat geen tweede mutable current-statepointer.

Een dossier begint zonder state (basisversie 0). Iedere succesvolle job voegt
precies één versie toe met predecessor, job, attempt, canonieke JSON-bytes,
SHA-256, vaste `cl100k_base`-tokenmeting en UTC-timestamp. De tabel heeft unieke
job-/attemptidentiteiten en een foreign key naar de vorige stateversie.
De opgeslagen canonieke JSON is de bron van waarheid, geen modelgeheugen.

`LeonardoStore.create_dossier(id, topic)` is idempotent voor dezelfde identiteit
met hetzelfde topic. `enqueue(operation_id, dossier_id, base_version,
[[part_id, revision], ...])` maakt expliciet één job. Dezelfde enqueue-identiteit
met exact dezelfde opdracht retourneert dezelfde job; gewijzigde argumenten
worden geweigerd. Dit is een lokale backendinterface, geen nieuwe publieke
automatische producer of MCP-aanmaaktool.

## Begrensde inputsnapshot

De assignment bevriest de vorige state, 1–32 expliciet gekozen revisies,
exact gereconstrueerde brontekst en hashes, rolcontract en outputcontract in
SQLite. Revisies moeten bij het dossiertopic horen. De normale provenance en
`revision_storage.reconstruct` controleren bytes, bronvolgorde, hashes en tokens.
Foreign keys naar de partrevisies blijven behouden. Het snapshot telt maximaal
35.000 `cl100k_base`-tokens en 250.000 UTF-8 bytes, inclusief beide contracten.
Dit is een backendpayloadgrens, geen bewijs over een toekomstige provider-
messagewrapper of modeltokenizer; een echte modeladapter moet de volledige
request nog meten volgens het modelcontract.

Reconstructie en tokenmeting vinden vóór de schrijflock plaats. Onder de korte
finale lock worden basisversie en afwezigheid van ready/running/blocked werk voor
hetzelfde dossier opnieuw gecontroleerd. Er kan slechts één onafgeronde
assignment per dossier ontstaan. De assignment en generieke job ontstaan atomair.

De `LeonardoProducer` is een ready-only adapter: `produce` creëert niets.
Bestaand ready werk blijft volgens fase 7 vóór nieuwe Sherlock-productie komen.
Een replay of recovery leest zijn contractsnapshot uit SQLite en heeft geen
actuele rolcontractfiles nodig. Iedere activatie krijgt de volledige relevante
persistente state opnieuw mee.

## Output en commit

`finish_weekendkrant_job` krijgt voor Leonardo `status=succeeded`,
`output_refs=[result_ref]` en `leonardo_state` als JSON-object. De backend eist:

- schema v1, exact dossier, volgende versie en juiste basisversie;
- afzonderlijke hypotheses, claims, onzekerheden en open vragen;
- stabiele item-IDs, tekst en expliciete revisiereferenties;
- claims onderscheiden `source_fact` en `inference`, met afzonderlijke
  ondersteuning en tegenbewijs; een bronfeit vereist ondersteuning;
- `processed_refs` is exact de unie van vorige verwerkte revisies en deze input;
- itemreferenties verwijzen uitsluitend naar die verwerkte revisies;
- maximaal 64 items per categorie, 256 verwerkte revisies, 4.000 vaste
  v1-tokens en 32.768 UTF-8 bytes voor de volledige canonieke outputstate.

Een rolling samenvatting wordt geen primaire bron. De backend valideert vorm,
identiteit, omvang en provenance, niet de inhoudelijke waarheid van claims.
Er is geen automatische truncatie of compressielus. Het cumulatieve maximum
van 256 revisies is een zichtbare v1-grens: overschrijding vereist later een
expliciet nieuw contract/archiveringsbeleid en verwijdert nu niets.

De bestaande claim-/leasecontrole en stateversie-CAS gebeuren onder dezelfde
lock als jobfinish, operation receipt en state-insert. Een validatiefout rolt de
hele mutatie terug; vorige state en running job blijven behouden. De executor
kan daarna zichtbaar failed/uncertain melden. Failed/uncertain vereisen
`output_refs=[]` en geen `leonardo_state`; abandon bewaart eveneens lege outputs. Geen van deze uitkomsten maakt state of bewaart
een toekomstige state-outputref.
Verlopen attempts blijven geblokkeerd; oude claims mogen niets committen.

Verloren finishantwoord: herhaal dezelfde operation-id met exact dezelfde
argumenten. De receipt retourneert het bevestigde resultaat zonder nieuwe
state. Ook een nieuwe operation-id met dezelfde claim/status/output/error en
exact dezelfde reeds bevestigde dossierstate is een no-op. Dossier, versie,
predecessor, job/attempt, canonieke content, hash en tokenmeting moeten gelijk
blijven, ook als inmiddels nieuwere state bestaat. Een inhoudelijke afwijking
blijft een conflict. Recovery gebruikt het bestaande operatorpad met bewijs
van gestopte uitvoering en gecontroleerde effecten: retry of failed. Losse recovery naar
succeeded is voor Leonardo verboden: succes en state moeten samen ontstaan.
Een retry krijgt dezelfde immutable input en een nieuwe gefencete attempt.

## Uitgestelde scope

Missievoorstellen en -administratie, dossieroverstijgende synthese,
bronherlezingsverzoeken, automatische offer-to-jobpolicy, providerkosten en
eindredactionele selectie volgen afzonderlijk. Deze slice voert geen
semantische dossierkeuze uit in Ariadne en consumeert bestaande offers niet.
Deployment vraagt schema 11, backendherstart, synchronisatie/publicatie van de
MCP-bridge en synchronisatie van `docs/agents/executor.md`; deze PR doet geen
productiedeployment of wijziging van de actieve scheduled task.

## Eerste fase-9-experiment

De [lokale operatorbrug en proefprocedure](phase-9-trial.md) selecteren expliciet
bestaande sealed offers en gebruiken bovenstaande enqueue- en finishprimitieven.
Dit voegt geen automatische routing of consumptiepolicy toe.
