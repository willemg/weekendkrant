# Ariadnes dagelijkse SQLite-verwerking

`Sherlock -> MCP ingress -> ingress_queue.pending -> Ariadne daily -> lokale draden -> ingress_queue.processed`

`./start_ariadne.sh daily` consumeert rechtstreeks de lokale SQLite-queue.
GitHub is geen Sherlock-transportqueue meer. De oude `closed`-manifestroute is
niet meer operationeel; geen fetch, weekbranch lookup, manifest of drie uur polling.
`prepare-week` en de bestaande weekworktreelogica blijven ongewijzigd voor verdere
redactionele/versioneringsoutput; zij zijn geen voorwaarde voor daily of Sherlock.

## Dagselectie en payloadcontract

De datum wordt eenmaal gekozen met `local_day()` in Europe/Brussels. Alleen
`pending` items met `payload.date` gelijk aan die lokale datum worden verwerkt.
Geen historische catch-up of toekomstige verwerking. Sherlock voert zijn dagelijkse
run uit vóór de bestaande cronstart om 10:00. Er is geen gereedmarker.

Een fiche is een JSON-object met **exact** deze velden:

```json
{
  "schema_version": 1,
  "topic": 2,
  "date": "2026-10-07",
  "content": "# Titel\n\nBronfiche met bronlinks."
}
```

`schema_version` is exact integer 1; `topic` is exact integer 1, 2 of 3.
Booleans, floats, extra/ontbrekende velden, dubbele JSON-sleutels, NaN en Infinity
worden geweigerd. `date` is een geldige ISO-kalenderdatum in exacte YYYY-MM-DD-vorm.
`content` is een niet-lege string; alleen whitespace is geen fiche. De oorspronkelijke
content wordt niet gestript of herschreven: exact UTF-8 encode bepaalt de fichebytes
én hun SHA-256. Ariadne synthetiseert geen Git-header.

Selectie leest pending records uit één DB-snapshot. Geldige andere kalenderdatums
worden overgeslagen vóór inhoudelijke fichevalidatie. Beschadigde JSON, een niet-object
of een ontbrekende/ongeldige datum kan niet veilig aan een andere dag worden toegewezen:
de run faalt dan expliciet met processing_error, zonder dat item te consumeren.
Dit voorkomt dat beschadigde pending records stil verdwijnen uit de dagselectie.
Eén ongeldige geselecteerde fiche faalt de hele dag vóór bestandspublicatie.

Nul pending fiches voor vandaag betekent `success` met nul draden. Een succesvol
dagrecord maakt iedere volgende daily een no-op, zonder extra poging, provenance
of bestanden. Ook bij een lege succesvolle dag blijven **late arrivals voor dezelfde
datum pending**. Er is geen late-arrival verwerking of heropening. Oudere pending
fiches blijven staan totdat een toekomstig expliciet beleid is gebouwd.

## Lokale draden en tokens

Outputpad blijft:
`/home/weekendkrant/draden/YYYY_Www/topic_N/YYYY-MM-DD_PPPP.txt`.
De bronidentiteit is `queue:<id>`, bijvoorbeeld `queue:2`. Topic en datum staan
structureel in draadmetadata; bronidentiteit, SHA-256 en byteaantal in elke bronafscheiding.
De inhoud tussen die afscheidingen is de exacte payload.content als UTF-8.
`received_at` wordt niet in de draad opgenomen.

Volgorde is numeriek topic, daarna lexicografisch bronidentiteit; `queue:10` sorteert
vóór `queue:2`. Delen starten op 1 per topic en dag. De volledige geserialiseerde
draad wordt gemeten met `tiktoken==0.12.0`, encoding `cl100k_base`: maximaal 30.000
tokens met 5.000 reserve binnen de totale modelruimte van 35.000. Iedere fiche blijft
heel. Past een fiche ook alleen niet, dan faalt de hele dag; geen truncatie,
semantische deduplicatie of modelcalls.

## Transactie en crashgedrag

Database: `/home/weekendkrant/weekendkrant.sqlite3`. `BEGIN IMMEDIATE` fixeert de
snapshot en houdt concurrerende SQLite-schrijvers tegen tot commit/rollback.
Dit is één korte dagelijkse verwerkingsflow, geen lease of extra processingstatus.
De bestaande clone_lock blijft als gedeeld, niet-blokkerend Ariadne-runtime-slot;
Git wordt alleen gebruikt om dat gemeenschappelijke slot te vinden, niet voor invoer.
`daily` inspecteert of synchroniseert geen worktrees en wijzigt app niet.

Alle payloads en het volledige draadplan worden gevalideerd vóór statuswijziging.
Daarna worden bestanden met tempfile + file-fsync + os.replace + directory-fsync
geschreven. Dezelfde SQLite-transactie registreert days.success, threads, sources,
het success-attempt en exact de gebruikte queue-IDs als processed. Pas daarna commit.
`days.commit_sha` en `days.manifest_sha256` blijven NULL. `sources.source_path`
bevat queue-identiteiten, geen Git-paden. IngressQueue.mark_processed commit niet zelf.

Een fout vóór of tijdens commit rollbackt alle DB-wijzigingen. Betrokken items
blijven pending, zonder gedeeltelijk geconsumeerde dag. Processing_error wordt
vervolgens in een aparte transactie geregistreerd. Bij een aanhoudende databasefout
kan ook die registratie mislukken; logging bewaart de fout en de CLI stopt niet-nul.

Filesystem en SQLite hebben geen gezamenlijke atomische commit. Een crash of
schrijffout kan al geschreven draadbestanden achterlaten terwijl queue-items pending
blijven en provenance ontbreekt. Alleen bestanden die in threads bij een succesvolle
dag geregistreerd zijn gelden als gepubliceerde output. Bij herhaling gebruiken
dezelfde snapshot en code dezelfde paden/bytes en worden bestanden veilig atomisch
overschreven. Als sinds de mislukte run nieuwe fiches zijn toegevoegd, wordt de nieuwe
dagsnapshot opnieuw volledig gepland. Er is geen distributed transaction of journalinglaag.
Na hard procesverlies kan het foutdagrecord ontbreken; de weekjob meldt dat als onvolledig.

## Weekvoorbereiding en auditretentie

`prepare-week` behoudt alle bestaande worktreecontroles, maximaal twee registraties,
veilig weigeren van lokale wijzigingen, locks en afwijkende paden. Alleen die taak
koppelt/wisselt de beheerde weekworktree. Daily heeft geen weekbranch nodig.
De zondagjob rapporteert de afgelopen week zonder dagfouten als blokkade te behandelen.
De bestaande auditretentie bewaart acht Belgische ISO-weken, met sources, threads,
attempts en days in één delete-transactie en daarna VACUUM. Deze retentie verwijdert
**geen ingress_queue-records**, ook geen processed items. Queue-retentie is buiten scope.
Lokale draden blijven opstartartefacten; zonder bewaarde provenance zijn ze geen actieve output.

## Migratie van bibib na merge

Als `app` nog op een ingressbranch staat, gebruik onderstaande veilige migratie.
Staat app al op main, werk die buiten een lopende Ariadne-run met `git pull --ff-only` bij. Voer als `weekendkrant`
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

Ga na de geslaagde migratie verder met de preflight hieronder. Er hoeft geen
weekworktree te worden aangekoppeld om daily te testen.

## Handmatig controleren op bibib

Voer als gebruiker weekendkrant, na merge en bijwerken van main, uit:

```bash
cd /home/weekendkrant/app
git status --short
git branch --show-current
.venv/bin/python -m pip install -r requirements.txt
export TIKTOKEN_CACHE_DIR=/home/weekendkrant/.cache/tiktoken
.venv/bin/python -c 'import tiktoken; print(tiktoken.get_encoding("cl100k_base").name)'
./start_tests.sh
```

De tokenizer wordt eenmalig gecached. Python 3.9+, Linux flock en SQLite zijn nodig.
Tests gebruiken tijdelijke SQLite-databases, outputdirectories en lokale Git-remotes;
geen echte productie-DB, GitHub of Cloudflare. Productie opent de DB pas bij daily.

Controleer vóór de echte run de huidige datum, dagstatus en queue:

```bash
.venv/bin/python - <<'PYCODE'
import sqlite3
from daily import DB_PATH, local_day
with sqlite3.connect(DB_PATH) as db:
    print('Lokale dag:', local_day())
    print('Dagrecord:', db.execute('SELECT day,status FROM days WHERE day=?',
                                  (str(local_day()),)).fetchone())
    for row in db.execute("SELECT id,status,json_extract(payload,'$.date') FROM ingress_queue ORDER BY id"):
        print(row)
PYCODE
./start_ariadne.sh daily
tail -n 40 /home/weekendkrant/logs/ariadne.log
```

De echte Sherlock-items van 7 oktober 2026 beginnen volgens de productiecontrole
bij ID 2; fictief item 1 is verwijderd. Controleer de werkelijk aanwezige IDs:
items voor vandaag horen pending te zijn vóór hun eerste daily. Een bestaand
success-dagrecord betekent bewust no-op, ook voor nu pending fiches. Verwijder of
reset zo'n record niet stilzwijgend. Na lokale middernacht verwerkt dit commando
7 oktober niet meer; gebruik geen productiecatch-up buiten dit contract.

Controleer daarna output en provenance:

```bash
.venv/bin/python - <<'PYCODE'
import hashlib
from pathlib import Path
import sqlite3
from daily import DB_PATH, local_day, token_count, LIMIT
with sqlite3.connect(DB_PATH) as db:
    day = str(local_day())
    print(db.execute('SELECT * FROM days WHERE day=?', (day,)).fetchone())
    print(db.execute('SELECT source_path,sha256 FROM sources WHERE day=?', (day,)).fetchall())
    print(db.execute('SELECT id,status FROM ingress_queue ORDER BY id').fetchall())
    for path, digest, tokens, reserve in db.execute(
            'SELECT path,sha256,tokens,reserved_tokens FROM threads WHERE day=?', (day,)):
        data = Path(path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert token_count(data.decode('utf-8')) == tokens
        assert tokens + reserve <= LIMIT
PYCODE
./start_ariadne.sh daily
```

De tweede run is een no-op; bestaande provenance en bestanden blijven behouden.
Late arrivals blijven pending. Productie mag uitsluitend de lokale actuele dag verwerken.

## Actieve Ariadne-cronjobs op bibib

Bestaande cronregels blijven ongewijzigd, hosttimezone Europe/Brussels:

```cron
0 10 * * * /home/weekendkrant/app/start_ariadne.sh daily >/dev/null
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

De dagelijkse job hoeft niet meer tot 13:00 te pollen. Geen nieuwe cronjobs,
Sherlock-aanpassing, API/plugin/tunnelwijzigingen of retentiebeleid voor de queue.
