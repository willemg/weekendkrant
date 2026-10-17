# Token- en kostenstrategie

De context-/tokenbudgetprincipes en bestaande bundelmetingen blijven relevant.
Leonardo als aparte voornaamste betaalde API-laag, de genoemde modelrollen en
API-dollarbudgettering zijn het oudere doelontwerp, geen huidige runtime.
Voor execution identity, scheduled capaciteit en gedeelde allowance
is het [ontwerpbesluit van 13 oktober 2026](intelligent-worker-orchestration.md)
leidend. Generieke jobopslag, MCP/control-plane, geïntegreerde jobproductie,
executor en dispatcher zijn geïmplementeerd. Alleen Sherlock produceert
momenteel automatisch nieuw werk; Leonardo en Kuifje gebruiken ready-only
adapters. Capaciteits- en kostenbeleid blijft verdere uitwerking vragen.

## Uitgangspunt

De grootste betaalde kost ontstaat wanneer intelligente modellen grote hoeveelheden context moeten lezen.

Weekendkrant probeert daarom niet de kwaliteit van de synthesizer maximaal te verlagen, maar de hoeveelheid irrelevante context die hij moet verwerken.

## Status en begrippen

De [huidige usage-audit](telemetry.md#modelgebruik-beschikbaarheid-van-echte-metingen)
ontsluit geen werkelijk modelverbruik: Sherlock/MCP en de beschikbare taakmetadata
leveren geen providerusage of product-allowanceteller. Telemetry toont dat expliciet
als onbekend (`unavailable`/`null`); lokale deterministische Ariadne is
`not_applicable`. De onderstaande bundelmetingen, inputgrenzen en oudere
API-kostenontwerpen zijn geen metingen van verbruik of resterende allowance.

De bundelmeting, Leonardo-state/jobs en de eerste echte scheduled Leonardo-
statecyclus zijn inmiddels geïmplementeerd. Historical recall en lokale audit per attempt zijn in fase 9.6 geïmplementeerd;
productiekarakterisering blijft een afzonderlijke operationele stap. Fase 12
implementeert immutable Kuifje-missies, uitvoering via de generieke dispatcher
en expliciete resultaatretour. Betrouwbare providerusage-/kostenadministratie
blijft gepland. Zie
[het geheugen- en orchestratieontwerp](leonardo-memory-and-orchestration.md).
De huidige bundels groeien over daggrenzen heen per ISO-week/topic via nieuwe
immutable revisies, totdat overflow of een expliciet lokaal offer de part sluit.
Een offer bevriest exact de actieve revisie en verwijst naar bestaande tokenmeting
en provenance, zonder bytes opnieuw te renderen. Offered/sealed is geen bewijs
van een Leonardo-call en veroorzaakt geen modelkosten. Automatische
offer-to-jobplanning volgt later; expliciete Leonardo-enqueue
bevriest nu al de complete context en contracten in een immutable assignment.

De oorspronkelijke 35K-grens was een arbitraire eerste cognitieve
chunkinghypothese: geef Leonardo niet zoveel nieuw, onbekend bronmateriaal
tegelijk dat hij zijn overzicht verliest. Het was geen kostenbudget. Fase 9.6
laat die hypothese bewust los om empirisch te ontdekken hoeveel nieuw materiaal
hij in één run goed structureel kan verwerken. De 1.048.576-token/8-MiB-grens is
uitsluitend een technische noodrem, evenmin een optimale behapbare brok.

Schema 12 vervangt de vroege 35K-assignmentgrens door een ruime lokale
technische fail-safe van 1.048.576 `cl100k_base`-tokens en 8 MiB UTF-8.
Dezelfde grens bewaakt per attempt startinput plus cumulatieve unieke recalls.
8 MiB begrenst allocatie/serialisatie; de afzonderlijke tokengrens beschermt tegen
tokenrijke payloads. De orde van grootte sluit aan bij maximaal 32 parts van
circa 30K tokens; dit blijft een lokaal gekozen noodrem. Dit is geen kostenoptimum en geen gemeten providerlimiet.
Werkelijke modelcapaciteit is nog onbekend; de grens is geen belofte dat iedere
payload door het scheduled model kan worden verwerkt. De circa-30K bundelgrens
blijft; state-output blijft maximaal 4K tokens en 32.768 bytes.

| Meting | Betekenis |
| --- | --- |
| Nieuwe broncontext | `new_part_count`, `new_part_tokens`, `new_part_bytes` en `new_parts`: geordende lijst met ref/tokens/bytes per aangeboden part, uitsluitend de exacte brontekst |
| Vorige state | `previous_state_tokens`: canonieke JSON van de state in het assignmentsnapshot, 0 zonder vorige state |
| Assignment-startinput | Canoniek immutable snapshot: contracten, vorige state en nieuwe parts |
| Recallcontext | Exacte gereconstrueerde brontekst, bytes/tokens per logische recall, op volgorde per attempt |
| Outputstate | Canonieke compacte nieuwe state, afzonderlijk gemeten |
| Providerusage/kost | Onbekend, inclusief model-ID, werkelijk input/output/reasoning/cachegebruik, allowance en geldkost |

`inspect --job ID --compact` toont deze lokale tellingen per attempt. Retry met
dezelfde recall_id/ref telt één logische read; herhaald transport kan extra
platformverbruik hebben dat niet lokaal meetbaar is. Een expired of failed
attempt krijgt geen fictieve nulrekening. Er is geen prijsberekening toegevoegd.

## Kost per component

### Sherlock

Sherlock draait als actieve ChatGPT-taak. Binnen het bestaande abonnement wordt zijn webvergaring beschouwd als marginale kost nul, zolang de relevante productlimieten niet worden overschreden.

Sherlock moet daarom al een eerste compacte broncompressie doen. Volledige webpagina's dumpen zou de latere API-kost onnodig verhogen.

### Ariadne

Ariadne draait lokaal en doet alleen deterministische verwerking. De marginale rekenkost is verwaarloosbaar.

### Leonardo

Leonardo is de eerste syntheselaag waarvan we nu de werkelijke contextappetijt
kunnen karakteriseren. De huidige scheduled uitvoeringsroute levert Weekendkrant
nog geen betrouwbare providerreceipt met model-ID, usage of geldkost; lokale
tokenmetingen blijven daarom capaciteits- en auditmetingen, geen factuur.

De experimentele basisstrategie wordt na de eerste echte run:

- meet iedere aangeboden component afzonderlijk: nieuwe parts, rolling state,
  instructies en iedere historical-recallresponse;
- behoud een ruime technische context/fail-safegrens, maar gebruik 35K voorlopig
  niet als vaste cognitieve chunkinghypothese voor Leonardo;
- houd de rolling state compact, zodat veel lezen niet automatisch veel blijvend
  geheugen betekent;
- verwerk grotere oogsten nog steeds progressief wanneer dat inhoudelijk of
  technisch nodig blijkt, maar karakteriseer eerst Leonardo's werkelijke
  informatieappetijt.

De bestaande circa-30K bronpart blijft een nuttige deterministische bundelgrens.
Zij is niet langer bedoeld als afleiding van een vaste 35K totale Leonardo-input.

De tussenoutput moet compact blijven. Leonardo hoeft na elke draad geen afgewerkt artikel te schrijven; hij kan een compacte research state bijwerken. Pas aan het einde volgt een langere synthese.

## Kuifje

Eén succesvolle Leonardo-finish kan 1..4 afzonderlijke immutable missies voor
hetzelfde topic opleveren. Die vormen samen één Kuifje-job/run met een ordered
missielijst en frozen context/contracten. De grenzen van 20 beoordeelde bronnen
en vijf fiches gelden per missie. De backend meet assignment en resultaten
lokaal; capaciteit wordt in jobstarts/runs geteld, niet in mission-count.

Bronfiches doorlopen de bestaande ingress-/partketen. Eén expliciet geselecteerde
terminale job/attempt levert daarnaast één `research_results`-item per missie
aan Leonardo, ook bij lege oogst of mislukking. Deze context is geen primair
bronbewijs en verruimt `processed_refs` niet. Zie [fase 12](phase-12-kuifje.md).
Missies, herlezing, retries en compressie moeten later onder dezelfde betrouwbare
providerusage-/budgetboekhouding vallen; die boekhouding is nog niet beschikbaar.

## Streaming synthese

In plaats van één grote request:

```text
hele week -> één gigantische synthese
```

wordt progressief gewerkt:

```text
state + draad 1 -> nieuwe state
state + draad 2 -> nieuwe state
state + draad 3 -> nieuwe state
...
laatste state -> weekendartikel
```

Daardoor blijft elke individuele call beheersbaar.

## Striktland

Striktland moet niet de hele Sherlock-oogst opnieuw lezen.

Idealiter koppelt Leonardo claims aan bron-id's of bronfragmenten. Striktland krijgt per controle alleen:

- de claim;
- relevante passage uit Leonardo's tekst;
- relevante bronfragmenten.

Daardoor kan een goedkoop model worden gebruikt en blijft de verificatiekost zeer laag.

## Minos

Minos ontvangt alleen foutieve of onvoldoende gedragen passages plus hun bronnen. Het krachtige model wordt dus alleen voor uitzonderlijke, kleine herstelrequests ingezet.

## Meten vóór uitvoeren

Ariadne moet met `tiktoken` de inputgrootte meten voordat een call naar Leonardo wordt gestart.

Dat maakt een kostenraming vooraf mogelijk:

```text
Sherlock-output deze periode
-> aantal benodigde draden
-> verwachte Leonardo-input
-> verwachte modelkost
```

Het geplande budgetmechanisme reserveert vóór uitvoering kosten voor begrensde
input, output en eventuele tool-/redeneerkosten, en rekent na uitvoering af met
werkelijke usage. Gelijktijdige aanvragen mogen hetzelfde budget niet dubbel
uitgeven. Tarieven, modelconfiguratie en ramingen worden geversioneerd; concrete
week- en maandgrenzen zijn nog te kiezen.

Historical recall moet vanaf de eerste implementatie afzonderlijk meetbaar zijn:
per job/attempt de gevraagde ref, teruggegeven bytes en lokaal gemeten tokens,
plus het cumulatieve recallvolume. Dat maakt de contextappetijt observeerbaar,
maar is nog geen providerrekening. Werkelijke input-, output-, reasoning- en
cached-inputusage en productallowance moeten uit een betrouwbare provider- of
platformbron komen en worden per attempt geboekt. Een expired of failed attempt
kan dus kosten hebben en mag niet uit de latere boekhouding verdwijnen.

Output houdt een afzonderlijke compacte grens; totale aangeboden context plus
gereserveerde output moet altijd binnen de technische contextcapaciteit van het
gekozen uitvoeringsmodel passen. De karakteriseringsfase kiest pas daarna een
lagere economische of kwaliteitsgrens als de metingen daar aanleiding toe geven.

## Dagelijkse bundeling versie 1

De implementatie legt `tiktoken==0.12.0` en `cl100k_base` expliciet vast, onafhankelijk
van veranderlijke modelnamen. De volledige geserialiseerde draad wordt gemeten,
inclusief draadheader, bronpaden, hashes, byteaantallen en bronafscheidingen.
Maximaal 30.000 tokens draad plus **5.000 gereserveerde tokens** voor alle overige
Leonardo-input samen: instructies, dossierstate, berichtenstructuur en API-overhead.

`run_daily()` verwerkt pending fiches tot en met vandaag per ISO-week/topic.
De open part groeit over daggrenzen via nieuwe immutable revisies. Nieuwe
bronnen volgen `(payload.date, numerieke queue-ID)` en worden achter bestaande
bronnen geplaatst. Overflow sluit de part definitief; splitsen gebeurt alleen
tussen hele fiches. Eén onmogelijke fiche faalt de hele snapshot zonder afkappen.
Ook identieke fiches blijven behouden. Provenance registreert per revisie de
volledige telling, tokenizer, reserve en exacte geordende bronmembership.

De 30.000 + 5.000-indeling hierboven is historische bundelmotivatie. Schema 12
heeft voor Leonardo het afzonderlijke ruime technische fail-safecontract zoals
hierboven beschreven. De circa-30K Ariadne-partgrens blijft deterministisch;
zij bepaalt geen optimale totale Leonardo-context. Voor installatie en caching
op bibib: zie [de dagelijkse preflight](daily-runtime.md).
