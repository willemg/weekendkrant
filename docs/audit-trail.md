# Audit trail en kwaliteitslabels

## Doel

De krant moet intern kunnen reconstrueren hoe een relevante feitelijke claim tot stand kwam.

Daarom krijgt iedere claim provenance: welke bronfiches eraan gekoppeld waren, welk model ze schreef, welke controle erop gebeurde en of een herschrijving nodig was.

## Twee auditlagen

Weekendkrant maakt onderscheid tussen twee soorten auditinformatie:

1. **versioneerbare bootstrapinformatie** die nodig is om een wekelijkse Git-werkruimte
   reproduceerbaar voor te bereiden;
2. **operationele verwerkingsaudit** van Ariadne en latere pipeline-stappen.

Het bestaande `ingress-preparation.json` blijft voor de eerste categorie in Git.
Voor de tweede categorie wordt een lokale SQLite-database gebruikt. Die database kan
bijvoorbeeld vastleggen welke ingressfiches gezien of verwerkt zijn, uit welke fiches
een draad bestaat, hoeveel tokens ervoor werden gemeten en welke pipeline-stap werd
uitgevoerd.

Tijdens de observatiefase is deze database lokale operationele staat en wordt ze niet
naar GitHub gecommit. Het definitieve schema wordt pas samen met de bundelimplementatie
vastgelegd.

## Operationele dagstatus (afgesproken ontwerp)

De dagelijkse Ariadne bewaart per lokale datum en ISO-week een operationele status
in `/home/weekendkrant/weekendkrant.sqlite3`. Deze registratie staat los van
claimkwaliteitslabels en van het Git-bootstraprecord. Het concrete SQLite-schema
en de technische statusnamen zijn nog te implementeren.

| Uitkomst | Betekenis |
| --- | --- |
| Geslaagd | Sherlock meldde klaar en Ariadne verwerkte de afgesloten oogst succesvol; ook een expliciet afgesloten lege oogst kan slagen. |
| Wachttijd verstreken | Na maximaal drie uur wachten was er geen geldige gereedmelding; de dagoogst is niet verwerkt. |
| Verwerking mislukt | De gereedmelding was beschikbaar, maar de verwerking slaagde niet. |
| Geen dagrecord | Er is geen bewijs van succesvolle verwerking; mogelijk startte de dagelijkse job niet. |

De zondagavondjob leest deze gestructureerde status om onvolledige dagen te herkennen;
logbestanden dienen voor diagnose en worden hiervoor niet geparseerd. Dagfouten en
ontbrekende records blokkeren de voorbereiding van de volgende week niet. Een
weekovergang wist of verhelpt de fouten niet, en start geen inhaalverwerking van
vorige weken.

## Minimale kwaliteitslabels

### verified_first_pass

Leonardo formuleerde de claim en Striktland vond voldoende ondersteuning in de aangeleverde bronnen.

### inference

De passage is geen rechtstreeks bronfeit maar een expliciet herkenbare synthese, interpretatie of gevolgtrekking.

### rewritten_by_minos

Striktland vond de oorspronkelijke formulering onvoldoende ondersteund of strijdig met de bronnen. Minos heeft de passage daarna één keer herschreven.

Er volgt geen tweede automatische verificatieronde.

## Voorbeeld

```text
claim_042
status: rewritten_by_minos
initial_model: terra
checker: luna
checker_result: unsupported
rewrite_model: sol
source_refs: S17, S22
```

Een claim die meteen slaagt:

```text
claim_017
status: verified_first_pass
initial_model: terra
checker: luna
checker_result: verified
source_refs: S03
```

## Geen oneindige regressie

De controleketen stopt bewust na Minos.

```text
Leonardo -> Striktland -> eventueel Minos -> klaar
```

Als Minos alsnog een fout maakt, blijft dat een aanvaard restrisico. Het auditlabel maakt zichtbaar dat de passage al een correctieronde heeft doorlopen.

Bij uitzonderlijke of spectaculaire claims kan de lezer daardoor gericht zelf naar het oorspronkelijke bronmateriaal teruggaan.

## Audit trail als producteigenschap

Het audit trail is niet alleen debugging-informatie. Het maakt zichtbaar:

- welke claims probleemloos door de eerste controle kwamen;
- waar een model gecorrigeerd moest worden;
- welke passages inferenties zijn;
- welke oorspronkelijke bronnen bij een claim horen.

Daarmee wordt bronprovenance een structureel onderdeel van Weekendkrant.

## Weekvoorbereiding (schema 1)

De eerste implementatie schrijft `audit/<jaar>_W<week>/ingress-preparation.json`:

```json
{
  "schema_version": 1,
  "week": "2026_W40",
  "branch": "ingress/2026_W40",
  "ingress_path": "ingress/2026_W40",
  "base_commit": "<volledige SHA van het uitgangscommit op de weekbranch>"
}
```

Dit registreert alleen de technische voorbereiding, geen verwerkte fiches,
bronverificatie of claimkwaliteitslabels. Het record krijgt geen kloktijd, zodat
herhaald uitvoeren dezelfde inhoud oplevert. Na commit maakt Git de wijziging
en het tijdstip traceerbaar. Een bestaand passend record blijft behouden,
ook na latere oogstcommits; een afwijkend record wordt geweigerd.
