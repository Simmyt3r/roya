create extension if not exists pgcrypto;
create extension if not exists pg_trgm;
create extension if not exists postgis;

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at=now();
  return new;
end;
$$;

create table if not exists public.profiles(
  id uuid primary key references auth.users(id) on delete cascade,
  name text,
  phone text,
  avatar_path text,
  platform_role text not null default 'user' check(platform_role in ('user','admin','support','finance')),
  status text not null default 'active' check(status in ('active','suspended','pending_verification')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.handle_new_auth_user()
returns trigger language plpgsql security definer set search_path=public as $$
begin
  insert into public.profiles(id,name)
  values(new.id,coalesce(new.raw_user_meta_data->>'name',''))
  on conflict(id) do nothing;
  return new;
end;
$$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_auth_user();

create table if not exists public.organizations(
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  status text not null default 'active' check(status in ('pending','active','suspended')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.organization_members(
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check(role in ('owner','manager','reservations','finance','staff')),
  status text not null default 'active' check(status in ('active','invited','suspended')),
  created_at timestamptz not null default now(),
  unique(organization_id,user_id)
);
create index if not exists idx_org_members_user on public.organization_members(user_id,status);

create table if not exists public.properties(
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  created_by_user_id uuid references auth.users(id),
  name text not null,
  slug text not null unique,
  description text not null default '',
  address text not null,
  city text not null,
  state text not null,
  country text not null default 'Nigeria',
  postal_code text,
  latitude double precision,
  longitude double precision,
  location geography(point,4326),
  phone text,
  email text,
  check_in_time time not null default '14:00',
  check_out_time time not null default '12:00',
  verification_status text not null default 'pending' check(verification_status in ('pending','verified','rejected','suspended')),
  verification_notes text,
  status text not null default 'draft' check(status in ('draft','active','inactive')),
  featured boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_properties_org on public.properties(organization_id);
create index if not exists idx_properties_market on public.properties(city,state,status,verification_status);
create index if not exists idx_properties_name_trgm on public.properties using gin(name gin_trgm_ops);
create index if not exists idx_properties_location on public.properties using gist(location);

create table if not exists public.property_images(
  id uuid primary key default gen_random_uuid(),
  property_id uuid not null references public.properties(id) on delete cascade,
  path text not null,
  alt_text text,
  sort_order integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists public.amenities(
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name text not null,
  category text
);

create table if not exists public.property_amenities(
  property_id uuid not null references public.properties(id) on delete cascade,
  amenity_id uuid not null references public.amenities(id) on delete cascade,
  primary key(property_id,amenity_id)
);

create table if not exists public.room_types(
  id uuid primary key default gen_random_uuid(),
  property_id uuid not null references public.properties(id) on delete cascade,
  name text not null,
  description text not null default '',
  capacity_adults integer not null default 2 check(capacity_adults>0),
  capacity_children integer not null default 0 check(capacity_children>=0),
  base_occupancy integer not null default 1 check(base_occupancy>0),
  total_inventory integer not null check(total_inventory>0),
  bed_configuration text,
  size_sqm numeric(8,2),
  status text not null default 'active' check(status in ('active','inactive')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(property_id,name)
);
create index if not exists idx_room_types_property on public.room_types(property_id,status);

create table if not exists public.room_images(
  id uuid primary key default gen_random_uuid(),
  room_type_id uuid not null references public.room_types(id) on delete cascade,
  path text not null,
  alt_text text,
  sort_order integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists public.physical_rooms(
  id uuid primary key default gen_random_uuid(),
  room_type_id uuid not null references public.room_types(id) on delete cascade,
  room_number text not null,
  floor text,
  status text not null default 'active' check(status in ('active','out_of_service','inactive')),
  unique(room_type_id,room_number)
);

create table if not exists public.rate_plans(
  id uuid primary key default gen_random_uuid(),
  room_type_id uuid not null references public.room_types(id) on delete cascade,
  name text not null,
  base_price_minor bigint not null check(base_price_minor>0),
  currency char(3) not null default 'NGN',
  guarantee_type text not null default 'pay_now' check(guarantee_type in ('pay_now','deposit','pay_at_property','hotel_approval')),
  refundable boolean not null default true,
  meal_plan text not null default 'room_only',
  deposit_percent integer not null default 100 check(deposit_percent between 0 and 100),
  min_stay integer not null default 1 check(min_stay between 1 and 90),
  cancellation_policy jsonb not null default '{}'::jsonb,
  status text not null default 'active' check(status in ('active','inactive')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(room_type_id,name)
);
create index if not exists idx_rate_plans_room on public.rate_plans(room_type_id,status);

create table if not exists public.rate_rules(
  id uuid primary key default gen_random_uuid(),
  rate_plan_id uuid not null references public.rate_plans(id) on delete cascade,
  starts_on date,
  ends_on date,
  days_of_week smallint[],
  minimum_stay integer,
  maximum_stay integer,
  booking_window_days integer,
  adjustment_type text check(adjustment_type in ('fixed','percent')),
  adjustment_value numeric(12,2),
  active boolean not null default true
);

create table if not exists public.daily_rates(
  id uuid primary key default gen_random_uuid(),
  rate_plan_id uuid not null references public.rate_plans(id) on delete cascade,
  date date not null,
  price_minor bigint not null check(price_minor>0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(rate_plan_id,date)
);

create table if not exists public.inventory_days(
  id uuid primary key default gen_random_uuid(),
  room_type_id uuid not null references public.room_types(id) on delete cascade,
  date date not null,
  total_inventory integer not null check(total_inventory>=0),
  held_inventory integer not null default 0 check(held_inventory>=0),
  sold_inventory integer not null default 0 check(sold_inventory>=0),
  price_override_minor bigint check(price_override_minor is null or price_override_minor>0),
  min_stay integer not null default 1 check(min_stay between 1 and 90),
  stop_sell boolean not null default false,
  closed_to_arrival boolean not null default false,
  closed_to_departure boolean not null default false,
  source text not null default 'manual' check(source in ('manual','roya','pms','ota','import')),
  version bigint not null default 1,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique(room_type_id,date),
  check(held_inventory+sold_inventory<=total_inventory)
);
create index if not exists idx_inventory_lookup on public.inventory_days(room_type_id,date);

create table if not exists public.reservations(
  id uuid primary key default gen_random_uuid(),
  reference text not null unique,
  organization_id uuid not null references public.organizations(id),
  property_id uuid not null references public.properties(id),
  user_id uuid references auth.users(id),
  guest_name text not null,
  guest_email text not null,
  guest_phone text not null,
  check_in date not null,
  check_out date not null,
  nights integer not null check(nights>0),
  adults integer not null check(adults>0),
  children integer not null default 0 check(children>=0),
  currency char(3) not null default 'NGN',
  total_price_minor bigint not null check(total_price_minor>=0),
  amount_due_minor bigint not null default 0 check(amount_due_minor>=0),
  amount_paid_minor bigint not null default 0 check(amount_paid_minor>=0),
  status text not null check(status in ('draft','held','pending_confirmation','confirmed','checked_in','checked_out','cancelled','no_show','expired')),
  payment_status text not null default 'unpaid' check(payment_status in ('unpaid','pending','partially_paid','paid','failed','partially_refunded','refunded')),
  guarantee_type text not null check(guarantee_type in ('pay_now','deposit','pay_at_property','hotel_approval')),
  expires_at timestamptz,
  cancellation_reason text,
  cancelled_at timestamptz,
  confirmed_at timestamptz,
  checked_in_at timestamptz,
  checked_out_at timestamptz,
  reminder_sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check(check_out>check_in)
);
create index if not exists idx_reservations_user on public.reservations(user_id,created_at desc);
create index if not exists idx_reservations_property on public.reservations(property_id,check_in,check_out,status);
create index if not exists idx_reservations_expiry on public.reservations(expires_at) where status in ('held','pending_confirmation');

create table if not exists public.reservation_items(
  id uuid primary key default gen_random_uuid(),
  reservation_id uuid not null references public.reservations(id) on delete cascade,
  room_type_id uuid not null references public.room_types(id),
  rate_plan_id uuid not null references public.rate_plans(id),
  quantity integer not null check(quantity>0),
  unit_price_minor bigint not null check(unit_price_minor>=0),
  total_price_minor bigint not null check(total_price_minor>=0),
  created_at timestamptz not null default now()
);

create table if not exists public.reservation_nights(
  id uuid primary key default gen_random_uuid(),
  reservation_id uuid not null references public.reservations(id) on delete cascade,
  reservation_item_id uuid not null references public.reservation_items(id) on delete cascade,
  room_type_id uuid not null references public.room_types(id),
  rate_plan_id uuid not null references public.rate_plans(id),
  date date not null,
  quantity integer not null check(quantity>0),
  unit_price_minor bigint not null check(unit_price_minor>=0),
  unique(reservation_item_id,date)
);
create index if not exists idx_reservation_nights_inventory on public.reservation_nights(room_type_id,date);

create table if not exists public.payments(
  id uuid primary key default gen_random_uuid(),
  reservation_id uuid not null unique references public.reservations(id) on delete cascade,
  amount_authorized_minor bigint not null default 0,
  amount_captured_minor bigint not null default 0,
  amount_refunded_minor bigint not null default 0,
  currency char(3) not null default 'NGN',
  status text not null default 'unpaid' check(status in ('unpaid','pending','partially_paid','paid','failed','partially_refunded','refunded')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.payment_transactions(
  id uuid primary key default gen_random_uuid(),
  reservation_id uuid not null references public.reservations(id) on delete cascade,
  provider text not null check(provider in ('paystack','flutterwave')),
  provider_reference text not null unique,
  amount_minor bigint not null check(amount_minor>0),
  currency char(3) not null,
  status text not null default 'initiated' check(status in ('initiated','pending','successful','failed','refunded','partially_refunded')),
  method text,
  raw_payload jsonb not null default '{}'::jsonb,
  paid_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_payment_transactions_reservation on public.payment_transactions(reservation_id,status);

create table if not exists public.refunds(
  id uuid primary key default gen_random_uuid(),
  reservation_id uuid not null references public.reservations(id),
  payment_transaction_id uuid references public.payment_transactions(id),
  provider_reference text,
  amount_minor bigint not null check(amount_minor>0),
  currency char(3) not null,
  status text not null check(status in ('requested','processing','successful','failed')),
  reason text,
  created_by_user_id uuid references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.payment_webhook_events(
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  event_key text not null,
  event_type text not null,
  signature_valid boolean not null default false,
  payload_json jsonb not null,
  processing_status text not null default 'received' check(processing_status in ('received','processed','ignored','failed')),
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  unique(provider,event_key)
);

create table if not exists public.channel_connections(
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  property_id uuid references public.properties(id) on delete cascade,
  channel text not null,
  status text not null default 'inactive' check(status in ('inactive','active','error','disconnected')),
  credentials_encrypted text,
  settings jsonb not null default '{}'::jsonb,
  last_synced_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.channel_room_mappings(
  id uuid primary key default gen_random_uuid(),
  connection_id uuid not null references public.channel_connections(id) on delete cascade,
  room_type_id uuid not null references public.room_types(id) on delete cascade,
  rate_plan_id uuid references public.rate_plans(id) on delete cascade,
  external_room_id text not null,
  external_rate_id text,
  unique(connection_id,external_room_id,external_rate_id)
);

create table if not exists public.channel_sync_logs(
  id uuid primary key default gen_random_uuid(),
  connection_id uuid not null references public.channel_connections(id) on delete cascade,
  direction text not null check(direction in ('push','pull')),
  resource_type text not null,
  status text not null check(status in ('success','failed','partial')),
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.reviews(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  property_id uuid not null references public.properties(id) on delete cascade,
  reservation_id uuid not null references public.reservations(id),
  rating smallint not null check(rating between 1 and 5),
  comment text not null default '',
  is_visible boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id,reservation_id)
);

create table if not exists public.notifications(
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  reservation_id uuid references public.reservations(id) on delete cascade,
  channel text not null check(channel in ('email','sms','whatsapp','in_app')),
  event_type text not null,
  recipient text not null,
  status text not null default 'queued' check(status in ('queued','sent','failed','cancelled')),
  payload jsonb not null default '{}'::jsonb,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.idempotency_keys(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  scope text not null,
  key text not null,
  request_hash text,
  response_json jsonb,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '24 hours',
  unique(user_id,scope,key)
);

create table if not exists public.audit_logs(
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid references auth.users(id),
  organization_id uuid references public.organizations(id),
  property_id uuid references public.properties(id),
  action text not null,
  entity_type text not null,
  entity_id text not null,
  before_json jsonb,
  after_json jsonb,
  ip_address inet,
  user_agent text,
  created_at timestamptz not null default now()
);
create index if not exists idx_audit_org_time on public.audit_logs(organization_id,created_at desc);
create index if not exists idx_audit_entity on public.audit_logs(entity_type,entity_id);

do $$
declare t text;
begin
  foreach t in array array['profiles','organizations','properties','room_types','rate_plans','daily_rates','reservations','payments','payment_transactions','refunds','reviews','channel_connections']
  loop
    execute format('drop trigger if exists %I on public.%I','trg_'||t||'_updated_at',t);
    execute format('create trigger %I before update on public.%I for each row execute function public.set_updated_at()','trg_'||t||'_updated_at',t);
  end loop;
end $$;

create or replace function public.create_reservation(
  p_user_id uuid,p_property_id uuid,p_room_type_id uuid,p_rate_plan_id uuid,
  p_check_in date,p_check_out date,p_quantity integer,p_adults integer,p_children integer,
  p_guest_name text,p_guest_email text,p_guest_phone text,p_guarantee_type text,p_idempotency_key text
)
returns table(
  reservation_id uuid,reference text,status text,payment_status text,total_price_minor bigint,
  amount_due_minor bigint,expires_at timestamptz,idempotent boolean
)
language plpgsql security definer set search_path=public as $$
declare
  v_existing jsonb;
  v_org_id uuid;
  v_capacity integer;
  v_rate public.rate_plans%rowtype;
  v_nights integer;
  v_count integer;
  v_min_available integer;
  v_total bigint;
  v_due bigint;
  v_reservation_id uuid:=gen_random_uuid();
  v_item_id uuid:=gen_random_uuid();
  v_reference text;
  v_status text;
  v_expires timestamptz;
  v_confirmed timestamptz;
begin
  if auth.uid() is not null and auth.uid()<>p_user_id then raise exception 'FORBIDDEN'; end if;
  if p_check_out<=p_check_in or p_quantity<1 then raise exception 'VALIDATION_ERROR'; end if;
  v_nights:=p_check_out-p_check_in;
  if v_nights>90 then raise exception 'VALIDATION_ERROR'; end if;

  select response_json into v_existing
  from public.idempotency_keys
  where user_id=p_user_id and scope='reservation_create' and key=p_idempotency_key and expires_at>now();
  if v_existing is not null then
    return query select
      (v_existing->>'reservation_id')::uuid,v_existing->>'reference',v_existing->>'status',
      v_existing->>'payment_status',(v_existing->>'total_price_minor')::bigint,
      (v_existing->>'amount_due_minor')::bigint,nullif(v_existing->>'expires_at','')::timestamptz,true;
    return;
  end if;

  select p.organization_id into v_org_id
  from public.properties p
  where p.id=p_property_id and p.status='active' and p.verification_status='verified';
  if v_org_id is null then raise exception 'PROPERTY_NOT_AVAILABLE'; end if;

  select capacity_adults into v_capacity
  from public.room_types where id=p_room_type_id and property_id=p_property_id and status='active';
  if v_capacity is null then raise exception 'ROOM_NOT_AVAILABLE'; end if;
  if p_adults>(v_capacity*p_quantity) then raise exception 'CAPACITY_EXCEEDED'; end if;

  select * into v_rate from public.rate_plans
  where id=p_rate_plan_id and room_type_id=p_room_type_id and status='active';
  if not found or v_rate.guarantee_type<>p_guarantee_type then raise exception 'RATE_NOT_AVAILABLE'; end if;
  if v_nights<v_rate.min_stay then raise exception 'RATE_NOT_AVAILABLE'; end if;

  perform 1 from public.inventory_days i
  where i.room_type_id=p_room_type_id and i.date>=p_check_in and i.date<p_check_out
  order by i.date for update;

  select count(*),min(i.total_inventory-i.held_inventory-i.sold_inventory)
  into v_count,v_min_available
  from public.inventory_days i
  where i.room_type_id=p_room_type_id and i.date>=p_check_in and i.date<p_check_out
    and not i.stop_sell and i.min_stay<=v_nights;

  if v_count<>v_nights or coalesce(v_min_available,0)<p_quantity then raise exception 'BOOKING_CONFLICT'; end if;
  if exists(select 1 from public.inventory_days where room_type_id=p_room_type_id and date=p_check_in and closed_to_arrival) then raise exception 'RATE_NOT_AVAILABLE'; end if;
  if exists(select 1 from public.inventory_days where room_type_id=p_room_type_id and date=p_check_out-1 and closed_to_departure) then raise exception 'RATE_NOT_AVAILABLE'; end if;

  select sum(coalesce(dr.price_minor,i.price_override_minor,v_rate.base_price_minor)*p_quantity)::bigint
  into v_total
  from public.inventory_days i
  left join public.daily_rates dr on dr.rate_plan_id=p_rate_plan_id and dr.date=i.date
  where i.room_type_id=p_room_type_id and i.date>=p_check_in and i.date<p_check_out;

  if p_guarantee_type='pay_now' then
    v_due:=v_total; v_status:='held'; v_expires:=now()+interval '15 minutes';
  elsif p_guarantee_type='deposit' then
    v_due:=ceil(v_total*v_rate.deposit_percent/100.0)::bigint; v_status:='held'; v_expires:=now()+interval '15 minutes';
  elsif p_guarantee_type='pay_at_property' then
    v_due:=0; v_status:='confirmed'; v_expires:=null; v_confirmed:=now();
  else
    v_due:=0; v_status:='pending_confirmation'; v_expires:=now()+interval '2 hours';
  end if;

  v_reference:='RYA-'||upper(substr(replace(v_reservation_id::text,'-',''),1,10));

  insert into public.reservations(
    id,reference,organization_id,property_id,user_id,guest_name,guest_email,guest_phone,
    check_in,check_out,nights,adults,children,currency,total_price_minor,amount_due_minor,
    status,payment_status,guarantee_type,expires_at,confirmed_at
  ) values(
    v_reservation_id,v_reference,v_org_id,p_property_id,p_user_id,p_guest_name,p_guest_email,p_guest_phone,
    p_check_in,p_check_out,v_nights,p_adults,p_children,v_rate.currency,v_total,v_due,
    v_status,'unpaid',p_guarantee_type,v_expires,v_confirmed
  );

  insert into public.reservation_items(id,reservation_id,room_type_id,rate_plan_id,quantity,unit_price_minor,total_price_minor)
  values(v_item_id,v_reservation_id,p_room_type_id,p_rate_plan_id,p_quantity,(v_total/v_nights/p_quantity),v_total);

  insert into public.reservation_nights(reservation_id,reservation_item_id,room_type_id,rate_plan_id,date,quantity,unit_price_minor)
  select v_reservation_id,v_item_id,p_room_type_id,p_rate_plan_id,i.date,p_quantity,
         coalesce(dr.price_minor,i.price_override_minor,v_rate.base_price_minor)
  from public.inventory_days i
  left join public.daily_rates dr on dr.rate_plan_id=p_rate_plan_id and dr.date=i.date
  where i.room_type_id=p_room_type_id and i.date>=p_check_in and i.date<p_check_out;

  if v_status='confirmed' then
    update public.inventory_days
    set sold_inventory=sold_inventory+p_quantity,version=version+1,updated_at=now()
    where room_type_id=p_room_type_id and date>=p_check_in and date<p_check_out;
  else
    update public.inventory_days
    set held_inventory=held_inventory+p_quantity,version=version+1,updated_at=now()
    where room_type_id=p_room_type_id and date>=p_check_in and date<p_check_out;
  end if;

  insert into public.payments(reservation_id,currency,status) values(v_reservation_id,v_rate.currency,'unpaid');

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(p_user_id,'reservation_create',p_idempotency_key,
    jsonb_build_object(
      'reservation_id',v_reservation_id,'reference',v_reference,'status',v_status,
      'payment_status','unpaid','total_price_minor',v_total,'amount_due_minor',v_due,
      'expires_at',coalesce(v_expires::text,'')
    )
  );

  return query select v_reservation_id,v_reference,v_status,'unpaid'::text,v_total,v_due,v_expires,false;
end;
$$;

create or replace function public.cancel_reservation(p_reservation_id uuid,p_user_id uuid,p_reason text)
returns table(reservation_id uuid,status text,payment_status text)
language plpgsql security definer set search_path=public as $$
declare v_r public.reservations%rowtype; v_n record;
begin
  select * into v_r from public.reservations where id=p_reservation_id and user_id=p_user_id for update;
  if not found or v_r.status not in ('held','pending_confirmation','confirmed') then raise exception 'RESERVATION_NOT_CANCELLABLE'; end if;
  for v_n in select room_type_id,date,quantity from public.reservation_nights where reservation_id=p_reservation_id loop
    if v_r.status='confirmed' then
      update public.inventory_days set sold_inventory=greatest(0,sold_inventory-v_n.quantity),version=version+1,updated_at=now()
      where room_type_id=v_n.room_type_id and date=v_n.date;
    else
      update public.inventory_days set held_inventory=greatest(0,held_inventory-v_n.quantity),version=version+1,updated_at=now()
      where room_type_id=v_n.room_type_id and date=v_n.date;
    end if;
  end loop;
  update public.reservations set status='cancelled',cancellation_reason=left(coalesce(p_reason,'Cancelled'),1000),cancelled_at=now(),expires_at=null
  where id=p_reservation_id;
  return query select p_reservation_id,'cancelled'::text,v_r.payment_status;
end;
$$;

create or replace function public.expire_reservation_holds()
returns table(expired integer)
language plpgsql security definer set search_path=public as $$
declare v_r record; v_n record; v_count integer:=0;
begin
  for v_r in
    select id from public.reservations
    where status in ('held','pending_confirmation') and expires_at is not null and expires_at<now()
    for update skip locked
  loop
    for v_n in select room_type_id,date,quantity from public.reservation_nights where reservation_id=v_r.id loop
      update public.inventory_days set held_inventory=greatest(0,held_inventory-v_n.quantity),version=version+1,updated_at=now()
      where room_type_id=v_n.room_type_id and date=v_n.date;
    end loop;
    update public.reservations set status='expired',expires_at=null where id=v_r.id;
    v_count:=v_count+1;
  end loop;
  return query select v_count;
end;
$$;

create or replace function public.record_successful_payment(p_provider_reference text,p_amount_minor bigint,p_payload jsonb)
returns table(reservation_id uuid,reservation_status text,payment_status text)
language plpgsql security definer set search_path=public as $$
declare v_tx public.payment_transactions%rowtype; v_r public.reservations%rowtype; v_new_paid bigint; v_payment_status text; v_n record;
begin
  select * into v_tx from public.payment_transactions where provider_reference=p_provider_reference for update;
  if not found then raise exception 'PAYMENT_REFERENCE_NOT_FOUND'; end if;
  select * into v_r from public.reservations where id=v_tx.reservation_id for update;

  if v_tx.status='successful' then
    return query select v_r.id,v_r.status,v_r.payment_status;
    return;
  end if;
  if p_amount_minor<>v_tx.amount_minor then raise exception 'PAYMENT_AMOUNT_MISMATCH'; end if;
  if v_r.status in ('cancelled','expired','checked_out') then raise exception 'RESERVATION_NOT_PAYABLE'; end if;

  update public.payment_transactions set status='successful',raw_payload=p_payload,paid_at=now() where id=v_tx.id;
  v_new_paid:=least(v_r.total_price_minor,v_r.amount_paid_minor+p_amount_minor);
  v_payment_status:=case when v_new_paid>=v_r.total_price_minor then 'paid' else 'partially_paid' end;

  if v_r.status in ('held','pending_confirmation') then
    for v_n in select room_type_id,date,quantity from public.reservation_nights where reservation_id=v_r.id loop
      update public.inventory_days
      set held_inventory=greatest(0,held_inventory-v_n.quantity),
          sold_inventory=sold_inventory+v_n.quantity,
          version=version+1,updated_at=now()
      where room_type_id=v_n.room_type_id and date=v_n.date;
    end loop;
  end if;

  update public.reservations
  set amount_paid_minor=v_new_paid,payment_status=v_payment_status,status='confirmed',
      confirmed_at=coalesce(confirmed_at,now()),expires_at=null
  where id=v_r.id;
  update public.payments set amount_captured_minor=v_new_paid,status=v_payment_status where reservation_id=v_r.id;
  return query select v_r.id,'confirmed'::text,v_payment_status;
end;
$$;

create or replace function public.is_org_member(p_org uuid)
returns boolean language sql stable security definer set search_path=public as $$
  select exists(
    select 1 from public.organization_members om
    where om.organization_id=p_org and om.user_id=auth.uid() and om.status='active'
  );
$$;

alter table public.profiles enable row level security;
alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;
alter table public.properties enable row level security;
alter table public.property_images enable row level security;
alter table public.room_types enable row level security;
alter table public.room_images enable row level security;
alter table public.rate_plans enable row level security;
alter table public.daily_rates enable row level security;
alter table public.inventory_days enable row level security;
alter table public.reservations enable row level security;
alter table public.reservation_items enable row level security;
alter table public.reservation_nights enable row level security;
alter table public.payments enable row level security;
alter table public.payment_transactions enable row level security;
alter table public.refunds enable row level security;
alter table public.reviews enable row level security;

drop policy if exists profiles_self_select on public.profiles;
create policy profiles_self_select on public.profiles for select using(id=auth.uid());
drop policy if exists profiles_self_update on public.profiles;
create policy profiles_self_update on public.profiles for update using(id=auth.uid()) with check(id=auth.uid());

drop policy if exists organizations_member_select on public.organizations;
create policy organizations_member_select on public.organizations for select using(public.is_org_member(id));
drop policy if exists organization_members_member_select on public.organization_members;
create policy organization_members_member_select on public.organization_members for select using(public.is_org_member(organization_id));

drop policy if exists properties_public_or_member_select on public.properties;
create policy properties_public_or_member_select on public.properties for select using((status='active' and verification_status='verified') or public.is_org_member(organization_id));
drop policy if exists property_images_public_select on public.property_images;
create policy property_images_public_select on public.property_images for select using(
  exists(select 1 from public.properties p where p.id=property_id and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id)))
);
drop policy if exists room_types_public_select on public.room_types;
create policy room_types_public_select on public.room_types for select using(
  exists(select 1 from public.properties p where p.id=property_id and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id)))
);
drop policy if exists rate_plans_public_select on public.rate_plans;
create policy rate_plans_public_select on public.rate_plans for select using(
  exists(select 1 from public.room_types rt join public.properties p on p.id=rt.property_id where rt.id=room_type_id and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id)))
);
drop policy if exists inventory_public_select on public.inventory_days;
create policy inventory_public_select on public.inventory_days for select using(
  exists(select 1 from public.room_types rt join public.properties p on p.id=rt.property_id where rt.id=room_type_id and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id)))
);

drop policy if exists reservations_owner_or_partner_select on public.reservations;
create policy reservations_owner_or_partner_select on public.reservations for select using(user_id=auth.uid() or public.is_org_member(organization_id));
drop policy if exists reservation_items_visible_select on public.reservation_items;
create policy reservation_items_visible_select on public.reservation_items for select using(
  exists(select 1 from public.reservations r where r.id=reservation_id and (r.user_id=auth.uid() or public.is_org_member(r.organization_id)))
);
drop policy if exists reservation_nights_visible_select on public.reservation_nights;
create policy reservation_nights_visible_select on public.reservation_nights for select using(
  exists(select 1 from public.reservations r where r.id=reservation_id and (r.user_id=auth.uid() or public.is_org_member(r.organization_id)))
);
drop policy if exists payments_visible_select on public.payments;
create policy payments_visible_select on public.payments for select using(
  exists(select 1 from public.reservations r where r.id=reservation_id and (r.user_id=auth.uid() or public.is_org_member(r.organization_id)))
);
drop policy if exists transactions_visible_select on public.payment_transactions;
create policy transactions_visible_select on public.payment_transactions for select using(
  exists(select 1 from public.reservations r where r.id=reservation_id and (r.user_id=auth.uid() or public.is_org_member(r.organization_id)))
);
drop policy if exists reviews_public_select on public.reviews;
create policy reviews_public_select on public.reviews for select using(is_visible=true or user_id=auth.uid());

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values
 ('property-images','property-images',true,10485760,array['image/jpeg','image/png','image/webp']),
 ('room-images','room-images',true,10485760,array['image/jpeg','image/png','image/webp']),
 ('verification-private','verification-private',false,15728640,array['image/jpeg','image/png','application/pdf']),
 ('avatars','avatars',true,5242880,array['image/jpeg','image/png','image/webp'])
on conflict(id) do nothing;

drop policy if exists public_property_images on storage.objects;
create policy public_property_images on storage.objects
for select using(bucket_id in ('property-images','room-images','avatars'));
