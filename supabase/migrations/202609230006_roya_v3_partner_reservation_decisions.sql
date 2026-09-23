create or replace function public.partner_decide_reservation(
  p_reservation_id uuid,
  p_approve boolean,
  p_reason text default null
)
returns table(
  reservation_id uuid,
  status text,
  payment_status text,
  confirmed_at timestamptz,
  cancelled_at timestamptz
)
language plpgsql
security definer
set search_path=public
as $$
declare
  v_r public.reservations%rowtype;
  v_n record;
  v_updated uuid;
begin
  select * into v_r
  from public.reservations
  where id=p_reservation_id
  for update;

  if not found
     or v_r.status<>'pending_confirmation'
     or v_r.guarantee_type<>'hotel_approval' then
    raise exception 'RESERVATION_NOT_DECIDABLE';
  end if;

  if v_r.expires_at is not null and v_r.expires_at<=now() then
    raise exception 'RESERVATION_EXPIRED';
  end if;

  if p_approve then
    for v_n in
      select room_type_id,date,quantity
      from public.reservation_nights
      where reservation_id=p_reservation_id
      order by date
    loop
      update public.inventory_days
      set held_inventory=held_inventory-v_n.quantity,
          sold_inventory=sold_inventory+v_n.quantity,
          version=version+1,
          updated_at=now()
      where room_type_id=v_n.room_type_id
        and date=v_n.date
        and held_inventory>=v_n.quantity
      returning id into v_updated;

      if v_updated is null then
        raise exception 'BOOKING_CONFLICT';
      end if;
      v_updated:=null;
    end loop;

    update public.reservations
    set status='confirmed',
        confirmed_at=coalesce(confirmed_at,now()),
        expires_at=null,
        updated_at=now()
    where id=p_reservation_id
    returning * into v_r;
  else
    for v_n in
      select room_type_id,date,quantity
      from public.reservation_nights
      where reservation_id=p_reservation_id
      order by date
    loop
      update public.inventory_days
      set held_inventory=greatest(0,held_inventory-v_n.quantity),
          version=version+1,
          updated_at=now()
      where room_type_id=v_n.room_type_id
        and date=v_n.date;
    end loop;

    update public.reservations
    set status='cancelled',
        cancellation_reason=left(coalesce(nullif(trim(p_reason),''),'Declined by property'),1000),
        cancelled_at=now(),
        expires_at=null,
        updated_at=now()
    where id=p_reservation_id
    returning * into v_r;
  end if;

  return query
  select v_r.id,v_r.status,v_r.payment_status,v_r.confirmed_at,v_r.cancelled_at;
end;
$$;

revoke all on function public.partner_decide_reservation(uuid,boolean,text)
from public, anon, authenticated;
