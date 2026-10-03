create extension if not exists pg_net;

do $$
begin
  if not exists (
    select 1 from vault.secrets where name='iroya_operations_scan_secret'
  ) then
    perform vault.create_secret(
      encode(gen_random_bytes(32),'hex'),
      'iroya_operations_scan_secret',
      'Bearer token for Supabase Cron to invoke the iRoya operations scanner'
    );
  end if;
end
$$;

select cron.schedule(
  'roya-operations-scan',
  '*/15 * * * *',
  $cron$
    select net.http_get(
      url:='https://iroya.vercel.app/api/internal/cron/operations-scan',
      headers:=jsonb_build_object(
        'Authorization',
        'Bearer ' || (
          select decrypted_secret
          from vault.decrypted_secrets
          where name='iroya_operations_scan_secret'
        )
      ),
      timeout_milliseconds:=10000
    ) as request_id;
  $cron$
);
