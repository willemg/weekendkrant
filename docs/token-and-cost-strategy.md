# Token- en kostenstrategie

## Uitgangspunt

De grootste betaalde kost ontstaat wanneer intelligente modellen grote hoeveelheden context moeten lezen.

Weekendkrant probeert daarom niet de kwaliteit van de synthesizer maximaal te verlagen, maar de hoeveelheid irrelevante context die hij moet verwerken.

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

Een later budgetmechanisme kan op basis hiervan een harde week- of maandgrens afdwingen.
