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
      timeout_milliseconds:=30000
    ) as request_id;
  $cron$
);
