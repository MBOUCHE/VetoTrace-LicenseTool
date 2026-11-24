# Prompt d'implémentation : licences VétoTrace v2

> À coller dans une session Claude Code ouverte sur `C:\Projets` (les dépôts `VetoTrace-LicenseTool`
> et `veto_track`). La référence est `docs/PLAN.md` de `VetoTrace-LicenseTool`.

---

Tu es chargé de transformer `VetoTrace-LicenseTool` en un véritable générateur de licences
pour les plans VétoTrace, et d'adapter l'application bureau pour qu'elle les applique.

**Lis d'abord, sans rien supposer :**
- `VetoTrace-LicenseTool/vetotrace_license.py` et `docs/PLAN.md` ;
- `veto_track/veto_track_api/apps/desktop/license.py`, `middleware.py`, `views.py`, `tests/test_desktop.py` ;
- `apps/licensing/models.py` (Plan, License), `services.py` (`compute_end_date`, `calculate_price`,
  `check_user_quota`), `permissions.py` (`module_required`), `management/commands/create_plan_fixtures.py` ;
- `apps/authentication/serializers.py` (`_MODULE_FLAGS`, `get_clinic_context`) ;
- `config/settings/desktop.py`.

**Outil éditeur (tâche 1)** : implémente le paquet décrit en section 4 du plan, avec le format v2 de la
section 3. Contraintes :
- Le catalogue reproduit **à l'identique** les slugs, quotas, modules et prix de `create_plan_fixtures`
  (`UNLIMITED = 100000` devient `0` = illimité dans la clé).
- Les dates et le prix reprennent **la même** logique que `licensing/services.py`.
- La clé privée ne doit jamais être écrite dans le dépôt. Le `.gitignore` exclut `*.pem` et `*.csv`.
- Ne casse pas les clés v1 existantes : `verify` les décode toujours.
- Le registre existant (colonnes `emise_le;titulaire;expire;poste;cle`) est migré sans perte.
- Utilise uniquement `cryptography` comme dépendance. `pytest` sert aux tests.

**Application (tâche 2)** : section 5 du plan. Contraintes CLAUDE.md :
- Aucun nouveau modèle, rôle ou migration. Le SaaS est strictement inchangé (le chemin bureau n'est
  actif que si `settings.DESKTOP_LICENSE_FILE` existe).
- v1 = accès complet. Un `v` inconnu, un `starts` futur ou une période de grâce dépassée = refus.
- Tests : modules refusés et autorisés selon la clé, quota d'utilisateurs, v1 rétrocompatible,
  période de grâce, `starts` futur.

**Vérification** : `pytest` dans l'outil ; `python manage.py check` puis `pytest apps/desktop
apps/licensing` dans l'API. Termine par la restitution de la section 6 de CLAUDE.md (fichiers,
migrations : aucune, tests et résultats, règles respectées, écarts reportés).
