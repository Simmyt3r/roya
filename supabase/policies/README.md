# RLS policies

RLS is declared in the versioned Supabase migration so migrations remain the single source of truth. Flask also performs explicit organization authorization because trusted server-side PostgreSQL connections may use a privileged role.
