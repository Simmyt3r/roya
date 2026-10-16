-- iRoya v1.0 release-candidate security drift correction.
-- These privileges were revoked previously but are currently granted again in production.
-- Keep PostGIS estimator RPCs server-only.

revoke execute on function public.st_estimatedextent(text,text)
from public, anon, authenticated;

revoke execute on function public.st_estimatedextent(text,text,text)
from public, anon, authenticated;

revoke execute on function public.st_estimatedextent(text,text,text,boolean)
from public, anon, authenticated;

grant execute on function public.st_estimatedextent(text,text) to service_role;
grant execute on function public.st_estimatedextent(text,text,text) to service_role;
grant execute on function public.st_estimatedextent(text,text,text,boolean) to service_role;
