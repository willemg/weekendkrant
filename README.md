# Weekendkrant

Weekendkrant is een experimentele, grotendeels geautomatiseerde nieuwsredactie voor een persoonlijk weekendmagazine.

Het systeem is bewust opgesplitst in een reeks smalle rollen:

- **Sherlock** verzamelt nieuws, doet een eerste lichte triage en vat bronnen compact samen.
- **Ariadne** is volledig deterministisch en vlecht Sherlocks output tot thematische draden met een harde tokenlimiet.
- **Leonardo** maakt van die draden inhoudelijke syntheses en verhalen.
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
- [Rollen: Sherlock, Ariadne, Leonardo, Striktland en Minos](docs/roles.md)
- [Token- en kostenstrategie](docs/token-and-cost-strategy.md)
- [Audit trail en kwaliteitslabels](docs/audit-trail.md)
- [Redactionele principes](docs/editorial-principles.md)

## Status

De ingress-API en persistente SQLite-queue zijn geïmplementeerd met uitsluitend
Python 3.9-standaardbibliotheek. Het doeltransport is
`Sherlock -> HTTPS ingress-API -> SQLite queue -> Ariadne`.
Git/GitHub dient voor code, weekbranches, worktrees, audit en krantartefacten,
niet als primaire transportqueue.

Ariadne `daily` consumeert rechtstreeks de SQLite-queue voor vandaag in
Europe/Brussels. Sherlock gebruikt de Weekendkrant Ingress MCP-plugin.
`Sherlock -> MCP ingress -> ingress_queue.pending -> Ariadne daily -> lokale draden -> ingress_queue.processed`
Nul pending fiches voor vandaag is een succesvolle lege run. Na succes worden de
gebruikte items `processed`; late arrivals blijven `pending`. Geen historische
catch-up, manifest of polling.
De nieuwe `ingress_tunnel.py` houdt een Cloudflare Quick Tunnel open en publiceert
de actuele URL als `config/ingress-endpoint.json` op GitHub `main`. De MCP-plugin
leest die vaste discoverypointer; Sherlock hoeft de tunnel-URL niet te kennen.
Zie [ingress-runtime](docs/ingress-runtime.md) voor starten, authenticatie,
de geïsoleerde publisher en de handmatig te installeren voorbeeld-unit.

## Dagelijkse queue en wekelijkse werkruimte

Zie [dagelijkse runtime en controles voor bibib](docs/daily-runtime.md).
De oude `closed`-manifestroute is niet meer operationeel. `prepare-week` blijft
voor redactioneel versiebeheer bestaan en is niet nodig voor Sherlock-transport.
De cronjobs blijven dagelijks om 10:00 en zondag om 22:00 Belgische tijd.
`app` blijft op `main`; `prepare-week` beheert maximaal één aparte weekworktree.
Beide taken gebruiken hetzelfde Ariadne-slot. De auditretentie is acht ISO-weken
maar ruimt geen queue-items op.

## Weekwerkruimte voorbereiden

Python 3.9 of nieuwer, Git en een lokale clone zijn vereist. Git 2.30.2 op bibib
wordt ondersteund; een Git-upgrade is niet nodig. Dagelijkse verwerking
gebruikt daarnaast de vastgelegde tokenizer uit `requirements.txt`.
De installatie staat onder `/home/weekendkrant/app`. Maak daar eenmalig de venv aan:

```bash
cd /home/weekendkrant/app
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Normale gebruikers en de actieve cronjobs starten Ariadne via `start_ariadne.sh`.
Beide uitvoerscripts gaan eerst naar de vaste repositoryroot en gebruiken rechtstreeks
`/home/weekendkrant/app/.venv/bin/python`; handmatig activeren van `.venv` is niet nodig.
Een ontbrekende venv/interpreter geeft een shellfout en een niet-nul exitcode.
Voer vanuit de repositoryroot uit:

```bash
./start_ariadne.sh prepare-week --date 2026-10-04
```

Dit bereidt `ingress/2026_W40` voor, met `ingress/2026_W40/.gitkeep`
en `audit/2026_W40/ingress-preparation.json`, en pusht de branch naar `origin`.
`--date` gebruikt exact de opgegeven kalenderdatum en de bijbehorende ISO-week.
De wekelijkse zondagavondtaak gebruikt in plaats daarvan:

```bash
/home/weekendkrant/app/start_ariadne.sh prepare-week --next-week
```

`--next-week` bepaalt de actuele datum expliciet in `Europe/Brussels` en kiest
de maandag van de eerstvolgende ISO-week. `--date` en `--next-week` zijn wederzijds
exclusief; één van beide is verplicht. De oude aanroep zonder subcommand vervalt.

De taak vereist een schone werkboom, haalt `origin` op en werkt lokale `main`
uitsluitend fast-forward bij tot `origin/main`. Nieuwe weekbranches beginnen op
die actuele `main`; bestaande lokale of remote weekbranches worden veilig hergebruikt
in de afzonderlijke weekworktree. Vóór een weekwissel wordt alleen die beheerde,
schone worktree via Git verwijderd. Branches en oogst blijven behouden. Extra
worktrees, lokale wijzigingen (ook genegeerde weekbestanden) of vergrendelde
worktrees leiden tot veilig stoppen.
Ariadne commit alleen de twee voorbereidingsbestanden indien nodig en pusht de
weekbranch met upstream. Git-identiteit en niet-interactieve lees-/schrijfauthenticatie
voor `origin` moeten vooraf zijn ingesteld. Alleen een geslaagde push geldt als succes.

Herhalen bewaart oogst en auditrecord en maakt geen nutteloze extra commit.
Een vuile werkboom, conflicterende metadata, divergente of lokaal vooruitgelopen
`main`, of divergente weekhistory leidt tot stoppen. Een vooruitgelopen weekremote
wordt uitsluitend fast-forward gevolgd; een lokale voorbereidingscommit na een
mislukte push kan bij weekvoorbereiding opnieuw worden gepusht.
Er is geen force-push, reset, automatische conflictmerge of weggooien van lokale
wijzigingen. Gebruik één schrijver per clone. Bij een pushfout blijft een gemaakte
commit lokaal behouden; na herstel van de fout kan dezelfde taak opnieuw worden uitgevoerd.

Runtime-meldingen verschijnen in `/home/weekendkrant/logs/ariadne.log`, met
automatische rotatie (1 MiB, vier reservebestanden; circa 5 MiB totaal).
Het JSON-resultaat blijft als gestructureerde CLI-output op stdout verschijnen.
De uitvoerende gebruiker moet de logmap kunnen aanmaken of erin kunnen schrijven;
zie [de loggingconfiguratie](docs/architecture.md#logging).

De handmatige preflight van `prepare-week --next-week` op `bibib` is geslaagd;
de weekbranch staat op GitHub en de wekelijkse cronjob is ingesteld voor zondag
om 22:00 Belgische tijd. Zie [het weekritme](docs/architecture.md#zondagavond-en-overgang-naar-de-volgende-week).

Dagelijks handmatig starten:

```bash
./start_ariadne.sh daily
```

Dit kiest vandaag in `Europe/Brussels` en verwerkt één consistente snapshot van
pending fiches voor die datum, zonder Git fetch of wachten op Sherlock.
De hele dag slaagt of faalt; zie [transactie en crashgedrag](docs/daily-runtime.md#transactie-en-crashgedrag).
Volg eerst de [preflight](docs/daily-runtime.md#handmatig-controleren-op-bibib).
De zondagjob rapporteert onvolledige dagen zonder de volgende week te blokkeren.

```bash
./start_tests.sh
```

Zie [de afbakening van deze stap](docs/architecture.md#eerste-implementatiestap-weekvoorbereiding)
en [het voorbereidingsrecord](docs/audit-trail.md#weekvoorbereiding-schema-1).
