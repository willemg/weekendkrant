Roep `start_weekendkrant_executor()` aan en bewaar de geretourneerde `executor_id`.

Roep `start_weekendkrant_executor({operation_id, activation_id})` aan. Bij een verloren of onzeker transportantwoord herhaal alleen exact dezelfde call met exact dezelfde argumenten.

Stop bij `claim:null`.

Valideer een ontvangen claim met `validate_weekendkrant_claim`. Stop als de claim niet geldig is.

Voer exact het ontvangen `role_contract` uit met de ontvangen `input`, `result_ref` en `output_contract`. Leid geen gedrag af uit de rolnaam en voer geen tweede job uit.

Volg voor verdere calls, side effects, finish of abandon exact de ontvangen contracten en de toolbeschrijvingen. Gebruik de ontvangen claim waar vereist. Houd argumenten bij transportretries exact gelijk. Stop na deze ene job.
