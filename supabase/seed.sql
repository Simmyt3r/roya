-- Roya initial demo seed.
-- Idempotent and safe to re-run. Demo property is clearly labelled as non-real.

insert into public.amenities(code,name,category) values
('wifi','Wi-Fi','connectivity'),
('parking','Parking','transport'),
('pool','Swimming Pool','leisure'),
('breakfast','Breakfast','food'),
('air_conditioning','Air Conditioning','room'),
('generator','Backup Power','utilities')
on conflict(code) do update set
  name=excluded.name,
  category=excluded.category;

insert into public.organizations(id,name,slug,status)
values(
  '10000000-0000-4000-8000-000000000001',
  'Roya Demo Hospitality',
  'roya-demo-hospitality',
  'active'
)
on conflict(id) do update set
  name=excluded.name,
  slug=excluded.slug,
  status=excluded.status,
  updated_at=now();

insert into public.properties(
  id,organization_id,name,slug,description,address,city,state,country,
  phone,email,verification_status,status,featured
) values(
  '20000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  'Roya Demo Hotel Lagos',
  'roya-demo-hotel-lagos',
  'Demonstration property for testing the Roya booking experience. This is not a real hotel and should not be used for an actual stay.',
  'Demo Property',
  'Lagos',
  'Lagos',
  'Nigeria',
  '+2340000000000',
  'demo@iroya.invalid',
  'verified',
  'active',
  true
)
on conflict(id) do update set
  name=excluded.name,
  slug=excluded.slug,
  description=excluded.description,
  address=excluded.address,
  city=excluded.city,
  state=excluded.state,
  country=excluded.country,
  phone=excluded.phone,
  email=excluded.email,
  verification_status=excluded.verification_status,
  status=excluded.status,
  featured=excluded.featured,
  updated_at=now();

insert into public.property_amenities(property_id,amenity_id)
select '20000000-0000-4000-8000-000000000001'::uuid,a.id
from public.amenities a
where a.code in ('wifi','parking','pool','breakfast','air_conditioning','generator')
on conflict do nothing;

insert into public.room_types(
  id,property_id,name,description,capacity_adults,capacity_children,
  base_occupancy,total_inventory,bed_configuration,size_sqm,status
) values
(
  '30000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  'Classic Room',
  'Comfortable demonstration room for one or two guests.',
  2,1,1,8,'1 Queen Bed',24,'active'
),
(
  '30000000-0000-4000-8000-000000000002',
  '20000000-0000-4000-8000-000000000001',
  'Deluxe Room',
  'Larger demonstration room with extra space and breakfast option.',
  2,1,2,5,'1 King Bed',34,'active'
),
(
  '30000000-0000-4000-8000-000000000003',
  '20000000-0000-4000-8000-000000000001',
  'Family Suite',
  'Demonstration suite for small families.',
  3,2,2,3,'1 King Bed + Sofa Bed',48,'active'
)
on conflict(id) do update set
  name=excluded.name,
  description=excluded.description,
  capacity_adults=excluded.capacity_adults,
  capacity_children=excluded.capacity_children,
  base_occupancy=excluded.base_occupancy,
  total_inventory=excluded.total_inventory,
  bed_configuration=excluded.bed_configuration,
  size_sqm=excluded.size_sqm,
  status=excluded.status,
  updated_at=now();

insert into public.rate_plans(
  id,room_type_id,name,base_price_minor,currency,guarantee_type,
  refundable,meal_plan,deposit_percent,min_stay,cancellation_policy,status
) values
(
  '40000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  'Flexible',
  3500000,'NGN','pay_at_property',true,'room_only',0,1,
  '{"demo":true,"summary":"Demo flexible rate. Not for a real stay."}'::jsonb,'active'
),
(
  '40000000-0000-4000-8000-000000000002',
  '30000000-0000-4000-8000-000000000002',
  'Bed & Breakfast',
  5500000,'NGN','pay_at_property',true,'breakfast',0,1,
  '{"demo":true,"summary":"Demo breakfast rate. Not for a real stay."}'::jsonb,'active'
),
(
  '40000000-0000-4000-8000-000000000003',
  '30000000-0000-4000-8000-000000000003',
  'Family Flexible',
  8000000,'NGN','hotel_approval',true,'breakfast',0,1,
  '{"demo":true,"summary":"Demo family rate requiring property approval."}'::jsonb,'active'
)
on conflict(id) do update set
  name=excluded.name,
  base_price_minor=excluded.base_price_minor,
  currency=excluded.currency,
  guarantee_type=excluded.guarantee_type,
  refundable=excluded.refundable,
  meal_plan=excluded.meal_plan,
  deposit_percent=excluded.deposit_percent,
  min_stay=excluded.min_stay,
  cancellation_policy=excluded.cancellation_policy,
  status=excluded.status,
  updated_at=now();

insert into public.inventory_days(room_type_id,date,total_inventory,source)
select room_type_id,d::date,total_inventory,'manual'
from (
  values
    ('30000000-0000-4000-8000-000000000001'::uuid,8),
    ('30000000-0000-4000-8000-000000000002'::uuid,5),
    ('30000000-0000-4000-8000-000000000003'::uuid,3)
) rooms(room_type_id,total_inventory)
cross join generate_series(current_date,current_date + interval '89 days',interval '1 day') d
on conflict(room_type_id,date) do update set
  total_inventory=excluded.total_inventory,
  source='manual',
  updated_at=now()
where public.inventory_days.sold_inventory + public.inventory_days.held_inventory <= excluded.total_inventory;
