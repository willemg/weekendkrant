Roep `start_weekendkrant_executor()` aan en bewaar de geretourneerde `executor_id`. Probeer bij een fout maximaal 3 keer, met 10 seconden tussen de pogingen. Als alle pogingen mislukken, meld de fout en stop.

Stop als `executor_id` null is.

Voer exact het ontvangen `role_contract` uit met de ontvangen `input`, `result_ref` en `output_contract`. Leid geen gedrag af uit de rolnaam en voer geen tweede job uit.

Volg voor verdere calls, side effects, finish of abandon exact de ontvangen contracten en de toolbeschrijvingen. Gebruik de ontvangen claim waar vereist. Houd argumenten bij transportretries exact gelijk. Stop na deze ene job.


Valideer een ontvangen claim met `validate_weekendkrant_claim`. Stop als de claim niet geldig is.