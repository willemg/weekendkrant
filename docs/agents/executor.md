# Generieke scheduled executor

Het canonieke runtime-artifact is [executor/instructions.md](../../executor/instructions.md).
Alleen die minimale tekst wordt aan de scheduled executor gegeven. Dit document
is menselijke architectuurdocumentatie, geen aanvullende runtime-instructie.

De executor meldt zich zonder argumenten aan, haalt met de ontvangen executor_id
het gebonden jobpakket op, valideert de claim, voert het immutable role_contract
uit en retourneert het resultaat volgens het output_contract. Hij kent geen
rollenlijst, klokberekening, scheduler-slot of technische operatie-identiteit.

Bibib bepaalt met zijn backendklok de logische occurrence en bewaart de
dispatchbeslissing in executor_activations. Binnen hetzelfde toegelaten slot
geeft iedere start dezelfde executor_id of dezelfde lege beslissing terug.
De startresponse bevat uitsluitend executor_id; jobophaling leest de bestaande
receipt en de autoritatieve attempt, zonder selectie, preparation of nieuwe claim.
Claimtokens blijven uitsluitend in attemptstate, nooit in receipts of audit.

Finish en abandon gebruiken één backend-afgeleide terminale operatie-identiteit
per job/attempt. Exacte retries replayen; gewijzigde payloads of een andere
terminale actie conflicteren. State en jobfinish blijven atomair. Bij een
onzeker finishantwoord wordt uitsluitend dezelfde terminale call herhaald;
inhoudelijk werk wordt niet opnieuw uitgevoerd.

De infrastructuur gebruikt voorlopig één uurlijkse scheduler, UTC-slots en een
symmetrische admissiontolerantie van 15 minuten. Dit leeft volledig op bibib in
executor_slot.py. Een nieuwe call buiten het venster krijgt executor_id:null.
Een vertraagde eerste call binnen een volgend venster behoort tot dat nieuwe
slot; zonder platformattest kan bibib de oorspronkelijke occurrence niet kennen.
Een reeds bevestigde beslissing wordt ook net buiten admission binnen hetzelfde
dichtstbijzijnde slot gereplayed. Een onbekende occurrence buiten admission krijgt
null; retries in een volgend slot zijn een nieuwe occurrence. De voorgeschreven
korte startretries vallen binnen één occurrence behalve bij een grensoverschrijding. Dit protocol garandeert één duurzame
job/attempt per logisch slot, geen exactly-once inhoudelijke uitvoering.
Receipts verlenen geen actuele machtiging: leases, validate, fencing en expliciet
herstel blijven autoritatief.
