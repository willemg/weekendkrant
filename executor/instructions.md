Roep `start_weekendkrant_executor()` aan en bewaar de geretourneerde `executor_id`. Probeer bij een fout maximaal 3 keer, met 10 seconden tussen de pogingen. Als alle pogingen mislukken, meld de fout en stop.

Stop als `executor_id` null is.

Roep `get_weekendkrant_job(executor_id)` aan en bewaar het geretourneerde jobpakket.

Valideer de ontvangen claim met `validate_weekendkrant_claim`. Stop als de claim niet geldig is.

Voer de instructies in het ontvangen `role_contract` uit met de ontvangen `input`, `result_ref` en `output_contract`.

Geef na uitvoering het resultaat met `finish_weekendkrant_job()` terug aan bibib volgens het ontvangen `output_contract` en stop.
