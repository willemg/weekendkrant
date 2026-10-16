# Sherlock via de generieke executor

Het actuele scheduled protocol staat in [dispatcher.md](dispatcher.md) en het
canonieke minimale runtime-artifact [executor/instructions.md](../executor/instructions.md).
De menselijke [executorbeschrijving](agents/executor.md) verklaart de
backendklok, occurrencebinding en replaygrenzen.

## Eén atomaire start

De publieke tool `start_weekendkrant_executor()` accepteert geen argumenten.
`POST /executor/start` en de oude route `/executor/sherlock/start` gebruiken
dezelfde server-owned bootstrap. De response bevat uitsluitend executor_id of
null. Jobophaling via `get_weekendkrant_job(executor_id)` leest de reeds gebonden
immutable opdracht; er is geen tweede dispatch of claim.

De algemene dispatcher kiest bestaand ready werk vóór nieuwe productie. Bij
Sherlock-productie maakt hij job, claim/attempt, run en immutable binding atomair.
De backend kiest het volgende topic en de lokale productiedatum, bewaakt cooldown,
pause, blocked state en capaciteit. Een lege beslissing verbruikt geen topic.
Voorbereiding leest contractbestanden alleen bij nieuwe productie buiten de
schrijflock; recovery en replay gebruiken bestaande snapshots.

## Concrete context en contracten

Het jobpakket bevat role, run_id, input={topic,date}, input_refs,
role_contract_ref met role_contract, output_contract_ref met output_contract,
result_ref en claim={job_id,attempt_id,token,lease_until}. De token wordt uit
job_attempts gelezen en verschijnt nooit in de activatiereceipt of auditmetadata.

De executor valideert de claim vóór inhoudelijke uitvoering. Bronregistraties en
fiches geven de claim mee; de backend controleert running-state, binding en lease
opnieuw onder de schrijflock. Een ontvangen leasewaarde is geen machtiging.
Job-backed runs mogen niet via de legacy finishroute worden afgesloten.

## Finish en herstel

Sherlock geeft zijn geleverde result_ref als enige output_refs terug.
finish_weekendkrant_job krijgt job_id, attempt_id, token, status, output_refs en
optioneel error, zonder een door het model gekozen operatie-ID. Run, attempt,
job en receipt sluiten atomair. Een exacte retry replayt; gewijzigde argumenten
conflicteren. Bij een onzeker antwoord wordt uitsluitend dezelfde finishcall
herhaald, nooit de inhoudelijke uitvoering.

Uncertain of abandon blokkeert voor operatoronderzoek. Expiry geeft geen
automatische toestemming tot heruitvoering. Expliciete recovery met bewijs kan
de bestaande job weer ready maken; een volgende attempt krijgt een nieuwe token
en run, met behoud van de immutable opdracht en contracten.

## Validatie en deploymentgrens

De gerichte fast-track controleert bootstrap, slotting, ready-first selectie,
replay, claimvalidatie, statefinish, recovery, crashes en de echte lokale
HTTP/SQLite/queue/Ariadne-keten. Pluginchecks blijven afzonderlijk opt-in en
vereisen Node uitsluitend in de pluginontwikkelomgeving.

Deze bronwijziging publiceert geen Sites-build, wijzigt geen live scheduled taak
en voert geen productiesmoke uit. Bij een latere expliciete deployment wordt
uitsluitend executor/instructions.md als scheduled instructie gebruikt.
