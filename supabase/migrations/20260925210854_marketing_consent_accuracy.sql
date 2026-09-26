-- A saved refusal is not a record of affirmative marketing consent.
alter table private.marketing_subscribers
  alter column consent_at drop not null,
  alter column consent_at drop default;
