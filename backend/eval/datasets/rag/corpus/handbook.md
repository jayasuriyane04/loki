# Meridian engineering handbook

## Overview
Meridian is the invoicing service behind the Atlas storefront. It creates invoices, sends payment reminders and
reconciles payments from the card processor every night at 02:00 UTC.

## Architecture
The API is written in Python with FastAPI and talks to a PostgreSQL 15 database. Background jobs run on a Redis
queue with three worker processes. PDF invoices are rendered by a separate renderer service.

## Billing rules
Invoices are due 30 days after they are issued. After a grace period of 5 days, an overdue invoice accrues a late
fee of 2% of the outstanding amount for every started month. Late fees are capped at 25% of the original amount.
Customers on the Enterprise plan are exempt from late fees.

## Currency handling
All amounts are stored as integers in minor units (cents). Conversions use banker's rounding (round half to even).
Zero-decimal currencies such as JPY and KRW are stored without a factor.

## Data retention
Invoices and payment records are kept for 7 years to meet tax rules. Webhook delivery logs are deleted after 90
days. Personal data in cancelled accounts is anonymised 30 days after cancellation.

## On-call
The on-call rotation changes every Monday at 10:00 local time. The primary on-call engineer must acknowledge a
page within 15 minutes. A SEV1 incident (customers cannot pay) requires a status page update within 30 minutes.
