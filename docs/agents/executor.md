# Generieke scheduled executor, eerste Sherlock-adapter

Voer per scheduled activatie maximaal één backendopdracht uit. Eén scheduler wordt
voorlopig eenmaal per uur gebruikt. Deze instructie is een deploymentartifact;
het bestand wijzigt of activeert geen bestaande scheduled taak.

1. Neem de stabiele occurrence-identiteit uit de schedulercontext. Een native
   occurrence-ID is geschikt. Anders gebruikt de operatoradapter de vaste naam
   `weekendkrant:scheduler-1:` plus het **geplande UTC-uurslot**, bijvoorbeeld
   `2026-10-15T12:00:00Z`. Dit is het oorspronkelijke geplande tijdstip, nooit de
   actuele tijd bij een retry of een nieuwe batch. Eén scheduler en één UTC-slot
   hebben steeds dezelfde activation_id. Gebruik `start:` plus die waarde als
   operation_id. Beide waarden blijven maximaal 128 tekens. Ontbreekt een
   betrouwbaar gepland tijdstip of occurrence-ID, stop zonder starttoolcall en
   meld ontbrekende schedulercontext. Verzin geen UUID of tijdstip.
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

De occurrence-identiteit is caller-supplied schedulercontext, geen cryptografisch
platformattest. De huidige MCP-authenticatie bewijst de private caller, niet een
native scheduler-occurrence. De backend bindt de opgegeven identiteit persistent,
weigert hergebruik en serialiseert Sherlockwerk. Productie-invoering vereist dat
de operator de stabiele occurrencecontext in de echte taak heeft gecontroleerd;
bij ontbrekende context blijft de taak uit. Dit document claimt geen reeds
geteste platforminjectie en verandert de gepauzeerde taak niet.
