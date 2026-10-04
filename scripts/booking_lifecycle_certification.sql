begin;

do $$
declare
  v_user uuid:=gen_random_uuid();
  v_org uuid:=gen_random_uuid();
  v_property uuid:=gen_random_uuid();
  v_room uuid:=gen_random_uuid();
  v_pay_now uuid:=gen_random_uuid();
  v_deposit uuid:=gen_random_uuid();
  v_pay_property uuid:=gen_random_uuid();
  v_approval uuid:=gen_random_uuid();
  v_approval_reject uuid:=gen_random_uuid();
  v_res record;
  v_settle record;
  v_decision record;
  v_inv record;
  v_ref text;
  d1 date:=current_date+40;
  d2 date:=current_date+50;
  d3 date:=current_date+60;
  d4 date:=current_date+70;
  d5 date:=current_date+80;
begin
  insert into auth.users(id,is_sso_user,is_anonymous)
  values(v_user,false,false);

  insert into public.organizations(id,name,slug,status)
  values(v_org,'Certification Hotel Group','certification-hotel-group-'||substr(v_org::text,1,8),'active');

  insert into public.organization_members(organization_id,user_id,role,status)
  values(v_org,v_user,'owner','active');

  insert into public.properties(
    id,organization_id,created_by_user_id,name,slug,address,city,state,
    verification_status,status
  ) values(
    v_property,v_org,v_user,'Certification Hotel',
    'certification-hotel-'||substr(v_property::text,1,8),
    '1 Certification Lane','Lagos','Lagos','verified','active'
  );

  insert into public.room_types(
    id,property_id,name,capacity_adults,capacity_children,total_inventory,status
  ) values(v_room,v_property,'Certification Room',2,2,1,'active');

  insert into public.rate_plans(
    id,room_type_id,name,base_price_minor,guarantee_type,deposit_percent,status
  ) values
    (v_pay_now,v_room,'Pay now',5000000,'pay_now',100,'active'),
    (v_deposit,v_room,'Deposit',5000000,'deposit',50,'active'),
    (v_pay_property,v_room,'Pay at property',5000000,'pay_at_property',100,'active'),
    (v_approval,v_room,'Hotel approval',5000000,'hotel_approval',100,'active'),
    (v_approval_reject,v_room,'Hotel approval reject',5000000,'hotel_approval',100,'active');

  insert into public.inventory_days(room_type_id,date,total_inventory)
  values
    (v_room,d1,1),(v_room,d1+1,1),
    (v_room,d2,1),(v_room,d2+1,1),
    (v_room,d3,1),(v_room,d3+1,1),
    (v_room,d4,1),(v_room,d4+1,1),
    (v_room,d5,1),(v_room,d5+1,1);

  select * into v_res from public.create_reservation(
    v_user,v_property,v_room,v_pay_now,d1,d1+2,1,1,0,
    'Certification Guest','certification@example.com','+2348000000000',
    'pay_now','cert-pay-now'
  );
  if v_res.status<>'held' or v_res.payment_status<>'unpaid'
     or v_res.amount_due_minor<>10000000 then
    raise exception 'CERT_PAY_NOW_CREATE_FAILED %',row_to_json(v_res);
  end if;

  select held_inventory,sold_inventory into v_inv
  from public.inventory_days where room_type_id=v_room and date=d1;
  if v_inv.held_inventory<>1 or v_inv.sold_inventory<>0 then
    raise exception 'CERT_PAY_NOW_HOLD_FAILED';
  end if;

  v_ref:='cert-pay-'||substr(gen_random_uuid()::text,1,12);
  insert into public.payment_transactions(
    reservation_id,provider,provider_reference,amount_minor,currency,status
  ) values(v_res.reservation_id,'paystack',v_ref,v_res.amount_due_minor,'NGN','initiated');

  select * into v_settle from public.record_successful_payment(
    v_ref,v_res.amount_due_minor,
    jsonb_build_object('status','success','amount',v_res.amount_due_minor)
  );
  if v_settle.reservation_status<>'confirmed' or v_settle.payment_status<>'paid' then
    raise exception 'CERT_PAY_NOW_SETTLEMENT_FAILED %',row_to_json(v_settle);
  end if;

  select * into v_settle from public.record_successful_payment(
    v_ref,v_res.amount_due_minor,
    jsonb_build_object('status','success','amount',v_res.amount_due_minor)
  );
  select held_inventory,sold_inventory into v_inv
  from public.inventory_days where room_type_id=v_room and date=d1;
  if v_inv.held_inventory<>0 or v_inv.sold_inventory<>1 then
    raise exception 'CERT_PAYMENT_REPLAY_FAILED';
  end if;

  select * into v_res from public.create_reservation(
    v_user,v_property,v_room,v_deposit,d2,d2+2,1,1,0,
    'Certification Guest','certification@example.com','+2348000000000',
    'deposit','cert-deposit'
  );
  if v_res.status<>'held' or v_res.amount_due_minor<>5000000 then
    raise exception 'CERT_DEPOSIT_CREATE_FAILED %',row_to_json(v_res);
  end if;

  v_ref:='cert-dep-'||substr(gen_random_uuid()::text,1,12);
  insert into public.payment_transactions(
    reservation_id,provider,provider_reference,amount_minor,currency,status
  ) values(v_res.reservation_id,'paystack',v_ref,v_res.amount_due_minor,'NGN','initiated');

  select * into v_settle from public.record_successful_payment(
    v_ref,v_res.amount_due_minor,
    jsonb_build_object('status','success','amount',v_res.amount_due_minor)
  );
  if v_settle.reservation_status<>'confirmed'
     or v_settle.payment_status<>'partially_paid' then
    raise exception 'CERT_DEPOSIT_SETTLEMENT_FAILED %',row_to_json(v_settle);
  end if;

  select * into v_res from public.create_reservation(
    v_user,v_property,v_room,v_pay_property,d3,d3+2,1,1,0,
    'Certification Guest','certification@example.com','+2348000000000',
    'pay_at_property','cert-pay-property'
  );
  if v_res.status<>'confirmed' or v_res.amount_due_minor<>0
     or v_res.payment_status<>'unpaid' then
    raise exception 'CERT_PAY_PROPERTY_CREATE_FAILED %',row_to_json(v_res);
  end if;

  select * into v_decision from public.cancel_reservation(
    v_res.reservation_id,v_user,'Certification cancellation'
  );
  if v_decision.status<>'cancelled' then
    raise exception 'CERT_PAY_PROPERTY_CANCEL_FAILED';
  end if;
  select held_inventory,sold_inventory into v_inv
  from public.inventory_days where room_type_id=v_room and date=d3;
  if v_inv.held_inventory<>0 or v_inv.sold_inventory<>0 then
    raise exception 'CERT_CANCEL_RELEASE_FAILED';
  end if;

  select * into v_res from public.create_reservation(
    v_user,v_property,v_room,v_approval,d4,d4+2,1,1,0,
    'Certification Guest','certification@example.com','+2348000000000',
    'hotel_approval','cert-approval'
  );
  if v_res.status<>'pending_confirmation' then
    raise exception 'CERT_APPROVAL_CREATE_FAILED';
  end if;

  select * into v_decision
  from public.partner_decide_reservation(v_res.reservation_id,true,null);
  if v_decision.status<>'confirmed' then
    raise exception 'CERT_APPROVAL_CONFIRM_FAILED';
  end if;
  select held_inventory,sold_inventory into v_inv
  from public.inventory_days where room_type_id=v_room and date=d4;
  if v_inv.held_inventory<>0 or v_inv.sold_inventory<>1 then
    raise exception 'CERT_APPROVAL_INVENTORY_FAILED';
  end if;

  select * into v_res from public.create_reservation(
    v_user,v_property,v_room,v_approval_reject,d5,d5+2,1,1,0,
    'Certification Guest','certification@example.com','+2348000000000',
    'hotel_approval','cert-approval-reject'
  );
  select * into v_decision
  from public.partner_decide_reservation(
    v_res.reservation_id,false,'Certification decline'
  );
  if v_decision.status<>'cancelled' then
    raise exception 'CERT_APPROVAL_REJECT_FAILED';
  end if;
  select held_inventory,sold_inventory into v_inv
  from public.inventory_days where room_type_id=v_room and date=d5;
  if v_inv.held_inventory<>0 or v_inv.sold_inventory<>0 then
    raise exception 'CERT_APPROVAL_REJECT_RELEASE_FAILED';
  end if;
end
$$;

rollback;
