create extension if not exists pg_cron;

select cron.schedule(
  'roya-expire-reservation-holds',
  '*/5 * * * *',
  $$select public.expire_reservation_holds();$$
);
