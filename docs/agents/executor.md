# Generieke scheduled executor, eerste Sherlock-adapter

Voer per scheduled activatie maximaal één backendopdracht uit. Eén scheduler wordt
voorlopig eenmaal per uur gebruikt. Deze instructie is een deploymentartifact;
het bestand wijzigt of activeert geen bestaande scheduled taak.

Iedere scheduleractivatie eindigt observeerbaar: ofwel door minstens de eerste
Weekendkrant-backendcall uit te voeren, ofwel door expliciet in zijn eigen
scheduled-run-output te rapporteren waarom die backendcall bewust niet is
uitgevoerd. Er bestaat geen silent no-op. Iedere beëindiging hieronder volgt
deze regel; een melding in de eigen run-output vereist geen backendcall.

Bij beëindiging vóór de eerste backendcall is een expliciete eindrapportage in
de eigen scheduled-run-output verplicht. Vermeld de reden en dat daarom geen
backendcall is uitgevoerd. Bij afwijzing buiten scheduler-admission vermeld je
minstens de verse geobserveerde tijd met timezone/UTC-offset, de normalisatie
naar UTC en dat de activatie buiten scheduler-admission viel. Als geen betrouwbare
timezone-aware klok verkrijgbaar is, vermeld je waarom de tijdwaarneming of
UTC-normalisatie onmogelijk of onbetrouwbaar was; verzin geen tijd of timezone.
Deze eindrapportage mag niet worden onderdrukt als een stille no-op.

1. Gebruik onze eigen logische scheduler-occurrence, geen platform-run-ID.
   Scheduler-ID is vast `weekendkrant:executor-1`, cadence exact uurlijks, slotbasis
   UTC. Observeer bij binnenkomst één verse betrouwbare timezone-aware huidige
   tijd en normaliseer die naar UTC. De klokbron hoeft niet zelf UTC te leveren.
   Een naïeve timestamp, alleen een datum of oude gesprekstimestamp volstaat
   niet. Ontbreekt een betrouwbare timezone-aware klok, voer geen backendcall uit
   en beëindig met de hierboven verplichte eindrapportage in de eigen run-output.
   Bepaal daarna het dichtstbijzijnde hele UTC-uur: rond naar beneden bij
   minder dan 30 minuten na het uur, anders naar boven (een exacte halfuurtie
   kiest het volgende uur). Gebruik exacte tijdsverschillen, geen floating point
   of lokale uurafronding. Admission geldt bij een absolute afstand van maximaal
   15 minuten tot dat slot, beide grenzen inclusief. Buiten deze tolerantie:
   voer geen backendcall uit en beëindig met de hierboven verplichte
   eindrapportage in de eigen scheduled-run-output, inclusief de geobserveerde
   verse tijd, timezone/UTC-normalisatie, afwijzing buiten scheduler-admission
   en de expliciete vermelding dat daarom geen backendcall is uitgevoerd.
   Vorm het UTC-slot als `YYYY-MM-DDTHH:00:00Z` en
   `activation_id=weekendkrant:executor-1:<slot>`, met
   `operation_id=start:<activation_id>`. Binnen de tolerantie volgt altijd de
   starttoolcall van stap 2, ook bij een vroege activatie vóór het hele uur.
   Bewaar beide waarden vóór de eerste startcall onveranderlijk voor de gehele
   uitvoering en alle transportretries, ook buiten de tolerantie of na een
   volgende uurovergang. Bereken voor een retry nooit opnieuw een slot.
   Bij hervatting zonder de oorspronkelijke IDs: geen nieuwe admission of
   backendcall; beëindig met de verplichte eindrapportage en vermeld dat de
   oorspronkelijke IDs ontbreken.
   Gebruik geen UUID, lokale tijd of actuele retrytimestamp. De symmetrische
   tolerantie van ±15 minuten is een voorlopige operationele parameter.
   De pure referentieadapter `executor_slot.start_arguments` beschrijft dezelfde
   regel; de cloudtaak voert dit contract uit en importeert geen Python van bibib.
2. Roep `start_weekendkrant_executor({operation_id, activation_id})` aan. Bij
   transporttimeout/verloren antwoord/503 herhaal exact dezelfde operatie met
   dezelfde twee IDs; voer geen inhoudelijk werk uit zolang de uitkomst onbekend
   is. De bridge genereert geen IDs en doet geen automatische retries.
3. Bij `claim:null` beëindig de uitvoering na deze backendbeslissing. Deze beslissing blijft voor deze activatie leeg, ook
   wanneer de baan later vrijkomt. Claim geen expliciete job en start geen legacy
   Sherlock-run als vervanging.
4. Bewaar de ontvangen claim `{job_id, attempt_id, token}` alleen binnen de
   uitvoering. Valideer via `validate_weekendkrant_claim`. `valid=false` betekent
   beëindiging van het werk na deze backendbeslissing, ook als de startreceipt eerder succes meldde. De receipt kan oud zijn.
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
8. Beëindig de uitvoering na die ene job. Geen tweede claim, nieuwe activatie-ID, topickeuze,
   zelfgestarte scheduler of algemene workselectie.

De grens van maximaal 15 onderliggende toolcalls per Code Mode-executie en het
bestaande expliciete safety-retrybeleid uit het rolcontract blijven gelden.
Onzekere netwerk-side effects vallen niet onder safety-retries. Claimtokens
komen nooit in rapportage, broninhoud of reproduceerbare publieke foutpayloads.

Deze identiteit is onze eigen logische UTC-occurrence, geen OpenAI-attest.
Platform-occurrence-metadata is niet vereist. Dubbele starts rond hetzelfde
logische uur delen activation/operation-ID en dus dezelfde persistente receipt.
Een volgend toegelaten uur is een andere logische activatie. UTC voorkomt DST-
ambiguïteit; klokfouten worden niet gecorrigeerd door dit protocol.

De tolerantie verwerpt afwijkende binnenkomsten buiten admission zonder
backendcall, met verplichte eindrapportage in de eigen scheduled-run-output. Een oude platform-run die pas binnen een volgend toegestaan uurvenster voor het eerst binnenkomt,
is zonder platformmetadata niet herkenbaar als oud: hij behoort uitsluitend tot
dat nieuwe logische slot. De invariant is maximaal één job/attempt per scheduler
per logisch slot, niet identificatie van alle oorspronkelijke platform-runs.

Receipts en fencing blijven autoritatief. Gelijktijdige callers kunnen dezelfde
claim terugkrijgen; validate is geen exclusieve executor-lock. Dit model bewijst
geen exactly-once inhoudelijke uitvoering of fichepublicatie. Een bekend dubbel
of reeds uitgevoerd resultaat mag niet opnieuw worden uitgevoerd; bij onzekere
side effects geldt uncertain/abandon/reconciliatie. Deze bestaande replaygrens
wordt door slotting niet opgelost of verruimd.
