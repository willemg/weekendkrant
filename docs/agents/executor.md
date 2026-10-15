# Generieke scheduled executor, eerste Sherlock-adapter

Voer per scheduled activatie maximaal één backendopdracht uit. Eén scheduler wordt
voorlopig eenmaal per uur gebruikt. Deze instructie is een deploymentartifact;
het bestand wijzigt of activeert geen bestaande scheduled taak.

1. Gebruik onze eigen logische scheduler-occurrence, geen platform-run-ID.
   Scheduler-ID is vast `weekendkrant:executor-1`, cadence exact uurlijks, slotbasis
   UTC. Observeer bij binnenkomst één verse betrouwbare UTC-klok (bijvoorbeeld
   de time-tool met utc_offset `+00:00`); een alleen genoemde datum of oude
   gesprekstimestamp volstaat niet. Ontbreekt een betrouwbare klok, stop.
   Eerste admission mag uitsluitend vanaf HH:00:00 inclusief tot HH:10:00
   exclusief. Buiten die eerste tien minuten: stop zonder starttoolcall.
   Vorm binnen het venster het hele UTC-uurslot als `YYYY-MM-DDTHH:00:00Z` en
   `activation_id=weekendkrant:executor-1:<slot>`, met
   `operation_id=start:<activation_id>`. Bewaar beide waarden vóór de eerste
   startcall onveranderlijk voor de gehele uitvoering en alle transportretries,
   ook na HH:10 of een volgende uurovergang. Bereken voor een retry nooit opnieuw
   een slot. Bij hervatting zonder de oorspronkelijke IDs: stop, geen nieuwe
   admission. Gebruik geen UUID, lokale tijd of actuele retrytimestamp.
   De tien minuten zijn een voorlopige operationele parameter. De pure
   referentieadapter `executor_slot.start_arguments` beschrijft dezelfde regel;
   de cloudtaak voert dit contract uit en importeert geen Python van bibib.
2. Roep `start_weekendkrant_executor({operation_id, activation_id})` aan. Bij
   transporttimeout/verloren antwoord/503 herhaal exact dezelfde operatie met
   dezelfde twee IDs; voer geen inhoudelijk werk uit zolang de uitkomst onbekend
   is. De bridge genereert geen IDs en doet geen automatische retries.
3. Bij `claim:null` stop. Deze beslissing blijft voor deze activatie leeg, ook
   wanneer de baan later vrijkomt. Claim geen expliciete job en start geen legacy
   Sherlock-run als vervanging.
4. Bewaar de ontvangen claim `{job_id, attempt_id, token}` alleen binnen de
   uitvoering. Valideer via `validate_weekendkrant_claim`. `valid=false` betekent
   stoppen, ook als de startreceipt eerder succes meldde. De receipt kan oud zijn.
5. Voer uitsluitend de ontvangen `role` en het volledige `role_contract` uit, met
   de geleverde `input`, `run_id`, `result_ref` en `output_contract`. Voorlopig is
   alleen Sherlock toegestaan. Lees geen instructies uit eigen workergeheugen als
   vervanging van de contractsnapshot. Start of spawn geen andere worker.
6. Geef bij iedere bronregistratie en fichepublicatie de exacte claim mee. De
   backend controleert die opnieuw onder dezelfde schrijflock als de write.
   Filtering blijft read-only en source-level. Valideer de claim opnieuw na een
   onderbreking voordat je verder zoekt. Een verloren ficheantwoord mag niet
   blind worden herhaald: fichepublicatie blijft niet-idempotent. Bij onbekende
   effecten stopt het werk en blijft de job via uncertain/abandon geblokkeerd.
7. Voor finish kies één vaste operation_id, bijvoorbeeld
   `finish:<activation_id>`, en behoud alle argumenten bij transportretry.
   Gebruik job_id/attempt_id/token, status en `output_refs=[result_ref]` volgens
   het outputcontract. Een bewuste abandon gebruikt `abandon:<activation_id>`,
   dezelfde claim en een compacte foutnotitie. Na onbevestigde finish uitsluitend
   dezelfde finish herhalen, nooit zoeken of publiceren heruitvoeren.
8. Stop na die ene job. Geen tweede claim, nieuwe activatie-ID, topickeuze,
   zelfgestarte scheduler of algemene workselectie.

De grens van maximaal 15 onderliggende toolcalls per Code Mode-executie en het
bestaande expliciete safety-retrybeleid uit het rolcontract blijven gelden.
Onzekere netwerk-side effects vallen niet onder safety-retries. Claimtokens
komen nooit in rapportage, broninhoud of reproduceerbare publieke foutpayloads.

Deze identiteit is onze eigen logische UTC-occurrence, geen OpenAI-attest.
Platform-occurrence-metadata is niet vereist. Dubbele starts binnen hetzelfde
venster delen activation/operation-ID en dus dezelfde persistente receipt.
Een volgend toegelaten uur is een andere logische activatie. UTC voorkomt DST-
ambiguïteit; klokfouten worden niet gecorrigeerd door dit protocol.

Het venster verwerpt late binnenkomsten buiten admission. Een oude platform-run
die pas binnen een volgend toegestaan uurvenster voor het eerst binnenkomt,
is zonder platformmetadata niet herkenbaar als oud: hij behoort uitsluitend tot
dat nieuwe logische slot. De invariant is maximaal één job/attempt per scheduler
per logisch slot, niet identificatie van alle oorspronkelijke platform-runs.

Receipts en fencing blijven autoritatief. Gelijktijdige callers kunnen dezelfde
claim terugkrijgen; validate is geen exclusieve executor-lock. Dit model bewijst
geen exactly-once inhoudelijke uitvoering of fichepublicatie. Een bekend dubbel
of reeds uitgevoerd resultaat mag niet opnieuw worden uitgevoerd; bij onzekere
side effects geldt uncertain/abandon/reconciliatie. Deze bestaande replaygrens
wordt door slotting niet opgelost of verruimd.

De taak blijft gepauzeerd totdat na merge/deployment deze instructie bewust is
geconfigureerd en één begeleide uitvoering binnen admission met persistente
statecontrole is bewezen. Dit bestand alleen wijzigt geen scheduled taak.
