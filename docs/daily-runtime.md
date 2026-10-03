# Ariadnes dagelijkse verwerking

`./start_ariadne.sh daily` verwerkt uitsluitend **vandaag in Europe/Brussels**.
Er is bewust geen `--date` voor deze taak: oude weken worden niet ingehaald.
De bestaande `prepare-week --date …` en `prepare-week --next-week` blijven bestaan.
Geen modelcalls, inhoudelijke beoordeling, deduplicatie of push van draden.

## Sherlocks afsluitcontract, versie 1

Op `ingress/YYYY_Www` staat per lokale datum precies één bestand:
`ingress/YYYY_Www/closed/YYYY-MM-DD.json`. Voorbeeld van een **lege**, succesvol
afgesloten oogst:

```json
{
  "schema_version": 1,
  "date": "2026-10-05",
  "week": "2026_W41",
  "files": []
}
```

Bij een niet-lege oogst bevat `files` exact alle fiches met die lokale `date`:

```json
{
  "schema_version": 1,
  "date": "2026-10-05",
  "week": "2026_W41",
  "files": [
    {
      "path": "ingress/2026_W41/ingress_0001.md",
      "sha256": "<64 kleine hextekens: SHA-256 van de exacte gepubliceerde bytes>"
    }
  ]
}
```

Het tweede voorbeeld is een sjabloon; de hashplaceholder is geen geldige hash.
Paden zijn relatief aan de repositoryroot; alleen `ingress_[0-9]+.md` direct in
de weekmap is toegestaan. Alle bestanden zijn gewone niet-uitvoerbare Git-blobs,
geen symlinks. Geen dubbele paden, dubbele JSON-sleutels of extra manifestvelden.

Sherlock publiceert dit manifest **als laatste**, pas nadat alle fiches succesvol
op de remote staan. Hij mag de afgesloten fiches en het manifest vervolgens niet
wijzigen, verwijderen of aanvullen. Bij onvolledige publicatie ontbreekt het manifest.
`files: []` betekent expliciet nul fiches; het ontbreken van een manifest betekent
nooit een lege oogst. Het manifest is geen bronfiche.

De ondersteunde bestaande ficheheader is UTF-8 met LF-regeleinden:

```text
WEEKENDKRANT-INGRESS-1
topic: 2
date: 2026-10-05

De volledige oorspronkelijke fiche, inclusief bronlinks.
```

`topic` is exact één van `1`, `2`, `3`, `4` uit Sherlocks vaste catalogus; nul,
onbekende nummers en afwijkende schrijfwijzen zoals `01` worden geweigerd. `date` is een geldige lokale
kalenderdatum in de betreffende ISO-week. De drie headerregels staan in deze
volgorde, zonder dubbele velden. Ariadne raadt geen metadata. Tijdens validatie
worden alle fiches in de weeksnapshot op geldig formaat gecontroleerd, maar alleen
de afgesloten datum wordt verwerkt. Een beschadigde fiche van een andere dag in
dezelfde snapshot leidt dus ook tot een expliciete verwerkingsfout.

Ariadne leest exacte Git-blobs uit één gefetchte commit. Ze controleert zowel de
snapshot waarin het manifest voor het eerst werd toegevoegd als de actuele snapshot:
alle genoemde fiches moeten toen al bestaan, hashes moeten overeenkomen, er mogen
geen extra fiches voor die datum bestaan en het manifest mag niet veranderd zijn.
Een ongeldige aanwezige melding is een `processing_error`, geen reden om verder te
wachten. Een eerder geslaagde dag is een no-op; die wordt niet opnieuw gevalideerd.

## Runtime en vergrendeling

Een cronstart om 10:00; meteen `fetch --prune origin` en controle van de remote huidige week.
Bij afwezigheid slaapt het proces 600 seconden en fetcht opnieuw. De monotone
wachttijd is maximaal 10.800 seconden vanaf het begin van de dagelijkse taak,
inclusief fetch en controles. Fetch krijgt de resterende tijd als subprocess-timeout.
Op of na de deadline wordt geen verwerking gestart. Een verwerking die ervoor
begon, mag later eindigen. Datum en ISO-week worden eenmaal bij start vastgelegd,
onafhankelijk van de hosttimezone en uitgecheckte branch. Klok en slaapfunctie
zijn injecteerbaar; tests slapen nooit echt.

Beide runtimefuncties nemen hetzelfde niet-blokkerende Linux `flock` op
`<git-common-dir>/ariadne.lock`. Het slot blijft ook tijdens polling vastgehouden;
een tweede Ariadne stopt zonder Git-wijzigingen. Het slotbestand mag blijven staan:
de kernel laat het slot bij afsluiten of crash vrij. Ook gekoppelde Git-worktrees
delen dit slot. Andere schrijvers moeten deze clone ongemoeid laten.

`/home/weekendkrant/app` moet op `main` blijven staan. De runtime weigert een
andere app-branch en verwijst naar de migratie hieronder. Alleen de afzonderlijke
`/home/weekendkrant/weekworktree` bevat de weekbranch. Beide taken worden altijd
met code, startscripts en venv uit `app` gestart; voer nooit scripts uit de
weekworktree uit. Bestaande ingressbranches krijgen geen rebase of codemerge.

Vóór fetch worden registratie en werkbomen gecontroleerd met
`git worktree list --porcelain` en `git status`. Maximaal twee geregistreerde
worktrees zijn toegestaan, uitsluitend de twee vaste paden. Onverwachte extra
worktrees worden niet opgeruimd: de taak stopt duidelijk.
Dit ondersteunt Git 2.30.2 zonder upgrade. De gedeelde parser leest regels en
Git-C-gequote paden (inclusief octale bytes), zonder splitsen op whitespace of
shell-evaluatie. Onbekende, dubbele of onvolledige records leiden tot stoppen.
Git 2.30.2 geeft paden ongequote weer; onduidelijke uitvoer, bijvoorbeeld een
pad met een ingebedde newline, wordt geweigerd. Omdat die versie geen `locked`
veld toont, controleert Ariadne ook het `locked`-bestand in de Git-adminmap van
de beheerde worktree. Ook een vergrendelde,
ontbrekende of verkeerd gekoppelde weekworktree wordt niet verwijderd.

De actuele weekbranch wordt in de weekworktree uitsluitend fast-forward gevolgd.
Een ontbrekende lokale weekbranch wordt een trackingbranch. Dagelijkse verwerking
weigert lokale voorsprong en divergentie. Zij kan een al bestaande huidige
remoteweek zelf aankoppelen, zonder eerst op zondagavond te moeten wachten.
Een geslaagde herhaling blijft een no-op, maar controleert wel beide werkbomen en
het aantal geregistreerde worktrees. Een fout bij die controle wist eerder
succes en provenance niet; de mislukte poging wordt apart geregistreerd.

De zondagavondjob verwijdert vóór een weekwissel alleen de beheerde schone
weekworktree, via `git worktree remove` zonder force. Ook untracked en genegeerde
bestanden tellen als lokale wijzigingen en blijven behouden bij weigering.
Branches en commits blijven bestaan. Een juiste worktree wordt gecontroleerd en
hergebruikt. Worktrees delen de Git-objectdatabase; het is geen volledige tweede
clone. Alle controles, verwijdering en creatie vallen onder hetzelfde slot.

## Lokale draden en tokens

Bestanden staan onder:
`/home/weekendkrant/draden/YYYY_Www/topic_N/YYYY-MM-DD_PPPP.txt`.
Ze bevatten draadmetadata, bronpad, SHA-256 en byteaantal, gevolgd door de volledige
fichebytes als UTF-8-tekst. Headers en bronlinks blijven behouden. De vaste volgorde
is numeriek topic, vervolgens lexicografisch volledig bronpad; deelnummer vanaf 1
per dag en topic. Geen semantische deduplicatie, ook niet bij identieke inhoud.
Oudere succesvolle dagen blijven beschikbaar. De SQLite-provenance bepaalt welke
bestanden volledig en succesvol gepubliceerd zijn; lees niet blind alle `.txt`-files.

`tiktoken==0.12.0` met expliciet `cl100k_base` meet de **volledige geserialiseerde
draad**, inclusief metadata en bronafscheidingen. Maximaal 30.000 tokens per draad;
5.000 van de totale 35.000 blijven gereserveerd voor latere instructies, dossierstate
en bericht-/API-overhead. De reserve is een maximum voor die hele aanvullende
context, geen toestemming om er onbeperkt tekst bij te voegen. Zie de
[tokenstrategie](token-and-cost-strategy.md#dagelijkse-bundeling-versie-1).

Ariadne vult een draad tot de volgende hele fiche niet meer past en begint dan een
nieuw deel. Past één fiche ook alleen niet, dan mislukt **de hele dag**, met bronpad
in de foutmelding. Er wordt niets afgekapt of stil overgeslagen. Er zijn nog geen
Leonardo-instructies, dossierstates of API-calls; voor toekomstige calls is een
controle van de werkelijk samengestelde modelinput verplicht.

## SQLite en foutafhandeling

Database: `/home/weekendkrant/weekendkrant.sqlite3`. Tabellen en crashgedrag staan
in [de auditdocumentatie](audit-trail.md#dagelijkse-sqlite-tabellen).
Een geldige lege oogst is succes met nul draden en nul bronnen.

Bij `prepare-week --next-week` rapporteert de weekjob alle zeven dagen van de
aflopende ISO-week: `timeout`, `processing_error` en ontbrekende records worden
als waarschuwingen gelogd. Zij blokkeren de volgende branch niet. De dagrecords en
poginghistoriek blijven binnen de achtwekenretentie behouden. Een gewone Git-fout of onleesbare database blijft
wel een runtimefout. Oude branches en late aanvullingen worden niet gewijzigd.

## Acht Belgische ISO-weken bewaren

Na het weekrapport en vóór de volgende weekvoorbereiding verwijdert de zondagjob
alle SQLite-records van vóór de maandag van de aflopende week minus zeven weken.
Dat bewaart de gerapporteerde week plus zeven voorgaande ISO-weken. Bijvoorbeeld:
rapport op 10 januari 2021 (2021_W01) bewaart vanaf maandag 16 november 2020
(2020_W47), inclusief 2020_W53. Het criterium gebruikt lokale kalenderdatums,
geen getalberekening op `YYYY_Www` en geen 56 dagen vanaf zondag.

Verwijdervolgorde in één transactie: `sources`, `threads`, `attempts`, `days`.
Ook foutstatussen en losse oude pogingen vervallen. Daarna voert de runtime buiten
de transactie `VACUUM` uit. Een verwijderfout rolt alle verwijderingen terug; een
VACUUM-fout wordt gelogd en stopt de job, terwijl de al gecommitte verwijderingen
geldig blijven. Een volgende uitvoering kan VACUUM opnieuw uitvoeren.

Draadbestanden worden niet opgeruimd. Bestanden waarvan de provenance door retentie
vervallen is, gelden niet automatisch als actieve output. De pipeline gebruikt
uitsluitend de bewaarde registratie van succesvolle dagen. Geen inhaalverwerking.

## Migratie van bibib na merge

De bestaande `app` kan nog op `ingress/2026_W41` staan. Voer als `weekendkrant`
onderstaand blok uit. Het stopt bij lokale wijzigingen, extra worktrees,
slotbezetting of een `main` die niet fast-forward tot `origin/main` kan komen.
Er worden geen wijzigingen weggegooid. Plan dit buiten een lopende Ariadne-run.

```bash
bash <<'SH'
set -euo pipefail
cd /home/weekendkrant/app
exec 9>"$(git rev-parse --git-common-dir)/ariadne.lock"
flock -n 9 || { echo 'Ariadne is actief; migratie gestopt.' >&2; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
    echo 'Vuile app-werkboom: bewaar wijzigingen vóór migratie.' >&2
    exit 1
fi
git fetch origin
# Gebruik de nieuwe gedeelde parser, ook als app nog oude ingresscode bevat.
inventory_code=$(mktemp /tmp/weekendkrant-inventory.XXXXXX.py)
trap 'rm -f "$inventory_code"' EXIT
git show origin/main:ariadne.py > "$inventory_code"
git worktree list --porcelain
.venv/bin/python - "$inventory_code" <<'PYCODE'
import runpy
import subprocess
import sys
parse = runpy.run_path(sys.argv[1])['parse_worktree_porcelain']
raw = subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], text=True)
paths = [record['worktree'] for record in parse(raw)]
allowed = {'/home/weekendkrant/app', '/home/weekendkrant/weekworktree'}
if not 1 <= len(paths) <= 2 or not set(paths) <= allowed:
    raise SystemExit('Onverwachte worktrees; controleer handmatig, niets opgeruimd.')
PYCODE
git merge-base --is-ancestor main origin/main || {
    echo 'Lokale main loopt vooruit of divergeert; migratie gestopt.' >&2
    exit 1
}
git switch main
git merge --ff-only origin/main
SH
```

Ga alleen verder als het migratieblok slaagt. Bereid de tokenizer en tests voor
zoals hieronder. Koppel daarna veilig de **bestaande huidige** Belgische week aan,
zonder push, weekrapport of retentie:

```bash
cd /home/weekendkrant/app
.venv/bin/python - <<'PYCODE'
from pathlib import Path
from ariadne import clone_lock, inspect_worktrees, ensure_week_worktree, _git
from daily import local_day
root = Path('/home/weekendkrant/app')
with clone_lock(root):
    inspect_worktrees(root)
    _git(root, 'fetch', 'origin')
    print(ensure_week_worktree(root, local_day()))
PYCODE
git worktree list --porcelain
git branch --show-current
./start_ariadne.sh daily --help
```

Verwacht `app` op `main` en precies één `weekworktree` op de actuele ingressbranch.
Een vuile weekworktree wordt niet vervangen; bewaar of commit de wijzigingen
eerst bewust. De dagelijkse taak voert dezelfde aankoppeling automatisch uit
wanneer ze nog ontbreekt. Start vervolgens de echte dagelijkse handmatige test.

## Handmatig controleren op bibib — vóór croninstallatie

Voer na de geslaagde migratie uit als gebruiker `weekendkrant`:

```bash
cd /home/weekendkrant/app
git status --short
git branch --show-current
.venv/bin/python -m pip install -r requirements.txt
export TIKTOKEN_CACHE_DIR=/home/weekendkrant/.cache/tiktoken
.venv/bin/python -c 'import tiktoken; print(tiktoken.get_encoding("cl100k_base").name)'
./start_tests.sh
```

Het tokenizerwoordenboek wordt bij deze preflight éénmalig opgehaald en lokaal
gecached. De startscripts gebruiken dezelfde persistente cache. Python 3.9+, Git,
Linux `flock`, SQLite uit de Python-standaardbibliotheek en de dependency uit
`requirements.txt` zijn nodig. Controleer de installatie daadwerkelijk op bibib;
de geautomatiseerde tests gebruiken lokale tijdelijke Git-remotes.

Bepaal datum en branch expliciet en bekijk eerst Sherlocks manifest:

```bash
DAY=$(.venv/bin/python -c 'from daily import local_day; print(local_day())')
WEEK=$(.venv/bin/python -c 'from daily import local_day; from ariadne import week_name; print(week_name(local_day()))')
git fetch origin
git show "origin/ingress/$WEEK:ingress/$WEEK/closed/$DAY.json"
./start_ariadne.sh daily
printf 'Exitcode: %s\n' "$?"
tail -n 40 /home/weekendkrant/logs/ariadne.log
```

Ontbreekt de melding, dan wacht het echte commando maximaal drie uur; gebruik de
tests voor snelle controle van het timeoutpad. Publiceer geen verzonnen gereedmelding
op de productietak. Laat Sherlock eerst met de
[exacte instructieaanvulling](sherlock-dagafsluiting.md) zijn echte oogst afsluiten.

Controleer status, pogingen, draden en provenance zonder extra SQLite-CLI:

```bash
.venv/bin/python - <<'PYCODE'
import sqlite3
from pathlib import Path
import hashlib
from daily import DB_PATH, token_count, LIMIT
with sqlite3.connect(DB_PATH) as db:
    for table in ('days', 'attempts', 'threads', 'sources'):
        print(table)
        for row in db.execute('SELECT * FROM ' + table):
            print(row)
    for path, digest, tokens, reserve in db.execute(
            'SELECT path,sha256,tokens,reserved_tokens FROM threads'):
        data = Path(path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert token_count(data.decode('utf-8')) == tokens
        assert tokens + reserve <= LIMIT
PYCODE
./start_ariadne.sh daily
git status --short
```

De tweede dagelijkse aanroep meldt `success` zonder extra provenance of output.
`git status` blijft schoon en `git branch --show-current` blijft `main`. Controleer
ook `git worktree list --porcelain`: maximaal twee registraties. De weekvoorbereiding kan daarna handmatig worden
getest met de bestaande `./start_ariadne.sh prepare-week --next-week`; dat commando
**pusht werkelijk** de volgende weekbranch. De tests dekken deze overgang eerst met
een tijdelijke lokale remote en een mislukte dag.

## Dagelijkse cronregel — alleen documentatie, nog niet installeren

Voor een host waarvan `timedatectl show -p Timezone --value` `Europe/Brussels` geeft:

```cron
0 10 * * * /home/weekendkrant/app/start_ariadne.sh daily >/dev/null
```

De bestaande zondagregel blijft:

```cron
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

Geen losse cronstart om de tien minuten en geen apart cronlog. De dagelijkse regel
wordt pas na de handmatige workflowtest geïnstalleerd; deze PR installeert niets en
wijzigt Sherlocks actieve ChatGPT-taak niet.
