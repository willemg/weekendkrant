# Weekendkrant

Weekendkrant is een experimentele, grotendeels geautomatiseerde nieuwsredactie voor een persoonlijk weekendmagazine.

Het systeem is bewust opgesplitst in een reeks smalle rollen:

- **Sherlock** verzamelt nieuws, doet een eerste lichte triage en vat bronnen compact samen.
- **Ariadne** is volledig deterministisch en vlecht Sherlocks output tot thematische draden met een harde tokenlimiet.
- **Leonardo** maakt van die draden inhoudelijke syntheses en verhalen en schrijft compacte dossierstate.
- **Kuifje** is de toekomstige onderzoeksreporter voor expliciete missies van Leonardo.
- **Striktland** controleert of feitelijke claims door het aangeleverde bronmateriaal worden gedragen.
- **Minos** herschrijft alleen wanneer Striktland een probleem vindt en velt daarmee het eindoordeel.

De kernprincipes zijn:

1. webvergaring zoveel mogelijk uitvoeren binnen reeds inbegrepen ChatGPT-capaciteit;
2. deterministische verwerking tussen verzameling en dure modelcalls plaatsen;
3. intelligente modellen zo weinig mogelijk irrelevante tokens laten lezen;
4. feitelijke claims traceerbaar houden naar bronmateriaal;
5. kwaliteitscontrole eindig houden: geen oneindige regressielussen;
6. de hele keten auditeerbaar maken.

Zie de ontwerpdocumentatie:

- [Architectuur](docs/architecture.md)
- [Rollen: Sherlock, Ariadne, Leonardo, Kuifje, Striktland en Minos](docs/roles.md)
- [Leonardo: geheugen, draden en deterministische regie](docs/leonardo-memory-and-orchestration.md)
- [Token- en kostenstrategie](docs/token-and-cost-strategy.md)
- [Audit trail en kwaliteitslabels](docs/audit-trail.md)
- [Redactionele principes](docs/editorial-principles.md)

## Huidige runtime

`Sherlock -> MCP ingress -> ingress_queue.pending -> Ariadne daily -> lokale draden -> ingress_queue.processed`

MCP/SQLite is de persistente ingressqueue. Pending items met `payload.date` tot en
met vandaag in `Europe/Brussels` blijven verwerkbaar totdat ze succesvol processed
zijn. De payloaddatum is provenance/ordening, geen eenmalig consumptievenster.
Een fout laat werk pending; de volgende geschikte run haalt het vanzelf in.
Geldige toekomstige fiches wachten. Een lege queue geeft success met nul draden.

Ariadne bundelt per **ISO-week + topic** en laat de open part over daggrenzen
groeien. Nieuwe fiches volgen `(payload.date, numerieke queue-ID)`; bestaande
bronnen blijven in hun opgeslagen volgorde. Overflow sluit de part definitief
en begint de volgende. Per week/topic is maximaal één part open.

Elke groei schrijft een nieuw immutable revisiebestand. SQLite bewaart het
exacte bronarchief, revisiehashes, tokenmetingen, bronposities en de actieve
revisie. De korte eindtransactie registreert alles samen met queue-status.
`PRAGMA user_version=1` migreert bestaande databases in-place zonder oude
rijen of dagbestanden te veranderen. Vanaf deze cut-over gebruiken nieuwe items
uitsluitend het partmodel; het eerste item maakt part 1/revision 1.
Zie [runtime en crashgedrag](docs/daily-runtime.md).

`daily` is de enige operationele Ariadne-taak. Er zijn geen Git-operaties,
weekbranches, beheerde weekworktree, weekrapport of automatische retentie nodig.
Het lokale runtime-slot staat buiten de applicatierepository. Historische Git-data
blijft behouden; bestaande SQLite-rijen worden niet opgeruimd en er is geen
automatische `VACUUM`. Leonardo-aanbieding, offered-lifecycle, dossiers, rolling state, Kuifje, modelcalls,
budgetten en eindredactionele planning volgen in afzonderlijke stappen.

De Quick Tunnel-component publiceert de actuele endpoint-URL via
`config/ingress-endpoint.json` op GitHub. De MCP-plugin leest die discoverypointer.
Zie [ingress-runtime](docs/ingress-runtime.md); tunnel/plugin/Sherlock veranderen
niet door deze cleanup.

## Installatie en uitvoering

Python 3.9 of nieuwer en de tokenizer uit `requirements.txt` zijn vereist.
De installatie staat onder `/home/weekendkrant/app`:

```bash
cd /home/weekendkrant/app
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start_tests.sh
./start_ariadne.sh daily
```

De wrappers gebruiken rechtstreeks de venv-interpreter; activeren is niet nodig.
JSON verschijnt op stdout, logging in `/home/weekendkrant/logs/ariadne.log`
(1 MiB, vier backups). DB, draden en runtime-lock staan buiten de applicatierepository.
Zie [preflight en croncontract](docs/daily-runtime.md#installeren-en-handmatig-controleren-op-bibib).

Verwijder na merge handmatig de obsolete zondagregel op bibib:

```cron
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

Behoud de dagelijkse regel:

```cron
0 10 * * * /home/weekendkrant/app/start_ariadne.sh daily >/dev/null
```

De code wijzigt geen crontab en verwijdert geen bestaande worktrees of branches.
