# Read-only telemetrybaseline

Op bibib gebruikt het bestaande startscript de venv en productie-DB:

```bash
./start_ariadne.sh telemetry
./start_ariadne.sh telemetry --hours 48
./start_ariadne.sh telemetry --db /tmp/weekendkrant.sqlite3 --hours 24
```

Lokaal, vanuit de repositoryroot, volstaat Python 3.9 of nieuwer zonder tokenizer:

```bash
python3 ariadne.py telemetry --db /tmp/weekendkrant.sqlite3
```

De output is JSON. `--hours` moet eindig en positief zijn (standaard 24).
De standaarddatabase is `/home/weekendkrant/weekendkrant.sqlite3`.
Telemetry opent uitsluitend een bestaand bestand met SQLite `mode=ro` en
`query_only=ON`, leest binnen één read-transactie en sluit de connection.
Geen migratie, fichevalidatie, materialisatie, runtime-lock of logginginitialisatie;
het commando maakt geen DB, logmap of outputbestanden aan. Het startscript blijft
ongewijzigd. SQLite kan tijdens de korte read-snapshot zijn normale leeslocks
nemen; telemetry gebruikt geen write-transactie en geen `immutable`-aanname.

## Betekenis van de metingen

- `as_of` en `sherlock_period` zijn UTC. Het Sherlock-venster omvat runs waarvan
  `started_at` tussen `since` en `until` ligt, inclusief beide grenzen.
- `registered_sources` telt de in de DB-snapshot geregistreerde sources van die
  runs, ongeacht wanneer hun review plaatsvond. Het is geen onafhankelijk venster
  op `reviewed_at`, geen fiche-aantal en geen telling van ongeopende kandidaten.
- Bronstatistieken van completed runs tellen ook completed runs met nul bronnen.
  Failed/running reviews tellen mee in het cohorttotaal en de topicverdeling,
  maar niet in completed-gemiddelden. Zonder completed runs zijn die statistieken
  `null`, niet nul. Topics 1, 2 en 3 worden afzonderlijk weergegeven.
- `published_fiches` telt alleen expliciete `sherlock_fiches`-koppelingen van de
  geselecteerde runs, ook bij failed/running runs. `by_run` bevat run-ID, topic,
  status, geregistreerde sources, fiche-aantal en geordende `queue_item_ids`.
  Publicatie betekent hier persistente ingressontvangst, niet publiek publiceren
  of succesvolle Ariadne-verwerking. Reviewaantallen worden niet vermenigvuldigd
  door het aantal fiches. `queue.unattributed_items` telt alle queue-items zonder
  expliciete producent, ongeacht het Sherlock-venster. Een nul fichetelling is
  nul bekende koppelingen; legacy-output is onbekend. Op schema 4 zonder mapping-
  tabel blijven fichemetingen `null` met waarschuwing; telemetry migreert niets.
- Looptijd is `finished_at - started_at` in seconden, uitsluitend voor completed
  runs met betrouwbare timestamps. Gemiddelde, mediaan en aantal geldige samples
  worden getoond. Er wordt geen actieve uitvoeringsduur uit `running` afgeleid.
- Queue en parts tonen de gehele huidige voorraad, onafhankelijk van `--hours`.
  Queue toont pending, processed en eventuele andere statussen. Het oudste pending
  item volgt ontvangsttijd, niet queue-ID of fichepayloaddatum; gelijke tijden
  gebruiken de kleinste ID. De leeftijd is tijd sinds ontvangst, geen verwerkingstijd.
- Parts toont tellingen per week/topic, open parts met exacte actieve revisie,
  tokenaantal, tokenizer en reserve, totaal aantal revisies en bestaande lokale
  offers. Een gesloten part is niet automatisch aangeboden. Een offer/seal is
  geen bewijs van uitgevoerde intelligentie.

Timestamps moeten een expliciete timezone bevatten. Ongeldige starttijden worden
met waarschuwing buiten het Sherlock-cohort gehouden. Negatieve of toekomstige
completed-looptijden worden niet geschat. Bij een onleesbare pending ontvangsttijd
is de echte oudste onbekend: `oldest_pending` wordt `null` met waarschuwing.
Een toekomstige oudste ontvangsttijd krijgt `age_seconds: null`.

Een lege database met bestaand schema geeft nul tellingen en lege lijsten;
een leeg bestand zonder schema geeft `null` per ontbrekende sectie en waarschuwingen,
zonder schema aan te maken. Ontbrekende tabellen, bijvoorbeeld op een oudere DB,
geven eveneens een onbeschikbare sectie. Een ontbrekend/onleesbaar bestand of
onbruikbaar schema geeft een expliciete CLI-fout op stderr en exitcode 1.

## Grenzen van de baseline

Schema 5 bevat een expliciete fiche→Sherlock-run-koppeling, maar geen generieke
jobkoppeling/-backlog en geen materialisatietimestamps of werkelijk modelgebruik.
Daarom kan dit rapport geen groei per tijdseenheid of allowancegebruik berekenen.
Ongeregistreerde reviews en producenten van legacy/ongekoppelde fiches zijn evenmin meetbaar.
De huidige tokenvoorraad is geen historische groeimeting. Het rapport meldt
deze beperkingen in `limitations`; een productiebasislijn moet nog verzameld worden.
Zie [fase 2 van het migratieplan](intelligent-worker-orchestration.md#fase-2--ontbrekende-telemetrie-bepalen).

Gerichte tests gebruiken uitsluitend tijdelijke databases met de bestaande
canonieke migraties als fixtureopbouw:

```bash
python3 -m unittest discover -s tests -p test_telemetry.py -v
```
