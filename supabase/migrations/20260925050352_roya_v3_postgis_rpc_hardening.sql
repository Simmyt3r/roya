revoke execute on function public.st_estimatedextent(text,text) from public,anon,authenticated;
revoke execute on function public.st_estimatedextent(text,text,text) from public,anon,authenticated;
revoke execute on function public.st_estimatedextent(text,text,text,boolean) from public,anon,authenticated;

grant execute on function public.st_estimatedextent(text,text) to service_role;
grant execute on function public.st_estimatedextent(text,text,text) to service_role;
grant execute on function public.st_estimatedextent(text,text,text,boolean) to service_role;
