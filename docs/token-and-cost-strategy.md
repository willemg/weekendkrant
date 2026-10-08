# Token- en kostenstrategie

## Uitgangspunt

De grootste betaalde kost ontstaat wanneer intelligente modellen grote hoeveelheden context moeten lezen.

Weekendkrant probeert daarom niet de kwaliteit van de synthesizer maximaal te verlagen, maar de hoeveelheid irrelevante context die hij moet verwerken.

## Status en begrippen

De bundelmeting is geïmplementeerd; Leonardo-calls, statebeheer, Kuifje-missies en
kostenadministratie zijn doelontwerp. Zie [het ontwerpbesluit van 8 oktober 2026](leonardo-memory-and-orchestration.md).
De huidige bundels groeien over daggrenzen heen per ISO-week/topic via nieuwe
immutable revisies, totdat overflow of een expliciet lokaal offer de part sluit.
Een offer bevriest exact de actieve revisie en verwijst naar bestaande tokenmeting
en provenance, zonder bytes opnieuw te renderen. Offered/sealed is geen bewijs
van een Leonardo-call en veroorzaakt geen modelkosten. Aanbiedplanning en de
callbouwer volgen later; logisch dossiergeheugen blijft daarvan onafhankelijk.

35K is een gekozen inputgrens, geen bewezen optimaal callvolume. Slow burn betekent
progressief nieuwe context verwerken met compacte state en tussenoutput. De winst
moet komen van minder herlezen en minder output; kleine calls of een trager ritme
maken dezelfde tokens niet vanzelf goedkoper. Herhaalde instructies, state en
compressiecalls tellen ook mee. Het aanbiedritme vereist kosten- en kwaliteitsmeting.

## Kost per component

### Sherlock

Sherlock draait als actieve ChatGPT-taak. Binnen het bestaande abonnement wordt zijn webvergaring beschouwd als marginale kost nul, zolang de relevante productlimieten niet worden overschreden.

Sherlock moet daarom al een eerste compacte broncompressie doen. Volledige webpagina's dumpen zou de latere API-kost onnodig verhogen.

### Ariadne

Ariadne draait lokaal en doet alleen deterministische verwerking. De marginale rekenkost is verwaarloosbaar.

### Leonardo

Leonardo is de voornaamste betaalde intelligentielaag.

De basisstrategie:

- standaard een kosten-efficiënt maar sterk model gebruiken, bijvoorbeeld Terra;
- per call een harde bovengrens instellen;
- de volledige Leonardo-input, dus draad plus dossierstate plus instructies, mag maximaal **35.000 tokens** bedragen;
- grotere oogsten worden progressief in meerdere draden verwerkt.

Een bruikbare verdeling kan bijvoorbeeld zijn:

```text
nieuwe draad          ~30k
rolling dossierstate   ~4k
instructies/metadata   ~1k
--------------------------
maximale input         35k
```

De tussenoutput moet compact blijven. Leonardo hoeft na elke draad geen afgewerkt artikel te schrijven; hij kan een compacte research state bijwerken. Pas aan het einde volgt een langere synthese.

## Kuifje (gepland)

Een missie krijgt alleen de vraag en relevante context. Resultaten keren met
missie- en dossieridentiteit terug naar Leonardo: geldige state + oorspronkelijke
missie + nieuwe bronnen. Oude broncontext wordt alleen gericht opnieuw opgehaald.
Missies, herlezing, retries en compressie vallen onder dezelfde budgetboekhouding.

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

De 35.000 geldt voor **input**. Output krijgt een afzonderlijke grens; input plus
gereserveerde output moet binnen de contextcapaciteit van het gekozen model passen.
De 5.000 reserve bevat alle overige input, inclusief state, missiecontext en
berichtoverhead. Een state rond maximaal 4K past dus alleen als ook de rest binnen
die reserve blijft. De callbouwer meet de complete request met de modeltokenizer;
een overschrijding leidt tot wachten of herverdeling van nog niet aangeboden
materiaal, nooit stilzwijgend afkappen of overschrijden.

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

Deze PR doet geen Leonardo-calls en kent nog geen definitieve instructies of
modelkeuze. De reserve is daarom een bindend budget voor de latere callbouwer.
Die moet de werkelijk samengestelde input opnieuw meten met de tokenizer van het
gekozen model, inclusief berichtoverhead, en een call boven 35.000 weigeren of de
input opnieuw laten verdelen. Een andere tokenizer of context boven de reserve
maakt de huidige draadindeling niet automatisch geschikt. De reserve mag nooit
stilzwijgend worden overschreden. Voor installatie en caching op bibib: zie
[de dagelijkse preflight](daily-runtime.md).
