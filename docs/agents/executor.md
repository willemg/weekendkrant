# Generieke scheduled executor

Voer per scheduled activatie maximaal één backendopdracht uit. Eén scheduler wordt
voorlopig eenmaal per uur gebruikt. Deze instructie is een deploymentartifact;
het bestand wijzigt of activeert geen bestaande scheduled taak.

Iedere activatie doet óf minstens de eerste Weekendkrant-backendcall, óf geeft
een korte expliciete eindmelding waarom geen backendcall werd uitgevoerd,
zonder interne automation-runtime-metadata bloot te leggen. Er bestaat geen
silent no-op. Iedere beëindiging hieronder volgt deze regel; een melding in de
eigen run-output vereist geen backendcall.

Bij beëindiging vóór de eerste backendcall is een korte expliciete eindmelding
in de eigen run-output verplicht: vermeld dát geen backendcall is uitgevoerd en
waarom. Bijvoorbeeld: “Geen backendcall uitgevoerd: de timingvoorwaarde kon niet
worden gevalideerd” of “Geen backendcall uitgevoerd: geen betrouwbare huidige
tijd beschikbaar”. Toon geen exacte tijd, timezone, UTC-offset, normalisatie,
schedule, interne IDs of andere interne automation-runtime-metadata. Deze
melding mag niet worden onderdrukt als een stille no-op.

1. Gebruik onze eigen logische scheduler-occurrence, geen platform-run-ID.
   Scheduler-ID is vast `weekendkrant:executor-1`, cadence exact uurlijks, slotbasis
   UTC. Observeer bij binnenkomst één verse betrouwbare timezone-aware huidige
   tijd en normaliseer die naar UTC. De klokbron hoeft niet zelf UTC te leveren.
   Een naïeve timestamp, alleen een datum of oude gesprekstimestamp volstaat
   niet. Ontbreekt een betrouwbare timezone-aware klok, voer geen backendcall uit
   en beëindig met de hierboven verplichte eindmelding in de eigen run-output.
   Bepaal daarna het dichtstbijzijnde hele UTC-uur: rond naar beneden bij
   minder dan 30 minuten na het uur, anders naar boven (een exacte halfuurtie
   kiest het volgende uur). Gebruik exacte tijdsverschillen, geen floating point
   of lokale uurafronding. Admission geldt bij een absolute afstand van maximaal
   15 minuten tot dat slot, beide grenzen inclusief. Buiten deze tolerantie:
   voer geen backendcall uit en beëindig met de hierboven verplichte
   korte eindmelding in de eigen run-output dat geen backendcall is uitgevoerd
   omdat de timingvoorwaarde niet kon worden gevalideerd, zonder interne metadata.
   Vorm het UTC-slot als `YYYY-MM-DDTHH:00:00Z` en
   `activation_id=weekendkrant:executor-1:<slot>`, met
   `operation_id=start:<activation_id>`. Binnen de tolerantie volgt altijd de
   starttoolcall van stap 2, ook bij een vroege activatie vóór het hele uur.
   Bewaar beide waarden vóór de eerste startcall onveranderlijk voor de gehele
   uitvoering en alle transportretries, ook buiten de tolerantie of na een
   volgende uurovergang. Bereken voor een retry nooit opnieuw een slot.
   Bij hervatting zonder de oorspronkelijke IDs: geen nieuwe admission of
   backendcall; beëindig met de verplichte korte eindmelding dat geen backendcall
   is uitgevoerd omdat veilig hervatten onmogelijk was, zonder interne IDs te tonen.
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
   de geleverde `input`, `result_ref` en `output_contract`, en eventuele
   rolspecifieke velden zoals `run_id` voor Sherlock. De backenddispatcher
   bepaalt welke rollen uitvoerbaar zijn; Sherlock en expliciet aangemaakte Leonardo-jobs zijn geregistreerd. Lees geen instructies uit eigen workergeheugen als
   vervanging van de contractsnapshot. Start of spawn geen andere worker.
6. Geef bij iedere bronregistratie en fichepublicatie de exacte claim mee. De
   backend controleert die opnieuw onder dezelfde schrijflock als de write.
   Filtering blijft read-only en source-level. Valideer de claim opnieuw na een
   onderbreking voordat je verder zoekt. Een verloren ficheantwoord mag niet
   blind worden herhaald: fichepublicatie blijft niet-idempotent. Bij onbekende
   effecten stopt het werk en blijft de job via uncertain/abandon geblokkeerd.
7. Voor finish kies één vaste operation_id, bijvoorbeeld
   `finish:<activation_id>`, en behoud alle argumenten bij transportretry.
   Gebruik job_id/attempt_id/token, status en output_refs volgens het outputcontract.
   Voor Leonardo geldt uitsluitend bij `succeeded`: `output_refs=[result_ref]`
   en de volledige outputstate als `leonardo_state` bij `finish_weekendkrant_job`.
   Bij Leonardo `failed` of `uncertain`: `output_refs=[]` en geen `leonardo_state`.
   De toekomstige result_ref bestaat bij die uitkomsten niet. De backend valideert
   en commit succesvolle state en finish atomair; abandon bewaart eveneens lege outputs.
   Een bewuste abandon gebruikt `abandon:<activation_id>`,
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
backendcall, met verplichte eindmelding in de eigen scheduled-run-output. Een oude platform-run die pas binnen een volgend toegestaan uurvenster voor het eerst binnenkomt,
is zonder platformmetadata niet herkenbaar als oud: hij behoort uitsluitend tot
dat nieuwe logische slot. De invariant is maximaal één job/attempt per scheduler
per logisch slot, niet identificatie van alle oorspronkelijke platform-runs.

Receipts en fencing blijven autoritatief. Gelijktijdige callers kunnen dezelfde
claim terugkrijgen; validate is geen exclusieve executor-lock. Dit model bewijst
geen exactly-once inhoudelijke uitvoering of fichepublicatie. Een bekend dubbel
of reeds uitgevoerd resultaat mag niet opnieuw worden uitgevoerd; bij onzekere
side effects geldt uncertain/abandon/reconciliatie. Deze bestaande replaygrens
wordt door slotting niet opgelost of verruimd.

De startbackend gebruikt de [algemene dispatcher](../dispatcher.md). Pause,
concurrency of ontbreken van uitvoerbare state kan duurzaam `claim:null` geven.
De executor interpreteert die keuze niet opnieuw en claimt geen vervangend werk.
