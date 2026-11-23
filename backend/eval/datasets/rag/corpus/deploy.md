# Deploying Meridian

## Environments
Staging deploys automatically from the main branch after the test suite passes. Production is deployed only from
tagged releases named vMAJOR.MINOR.PATCH, and only between Monday and Thursday.

## Database migrations
Migrations run before the new code is deployed. Every migration must stay backward compatible with the previous
release for one full release cycle, so a rollback never needs a down-migration.

## Rollback
If error rates rise after a release, roll back with `meridian-cli rollback --to <tag>`. Rollbacks must be started
within 30 minutes of the alert, and the incident channel must be told the tag you rolled back to.

## Secrets
Secrets live in Vault under secret/meridian/<environment>. They are never stored in the repository or in CI
variables. Access tokens for Vault expire after 8 hours.
