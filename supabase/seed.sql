-- Development-only reference data. Do not run automatically in production.
insert into public.amenities(code,name,category) values
('wifi','Wi-Fi','connectivity'),
('parking','Parking','transport'),
('pool','Swimming Pool','leisure'),
('breakfast','Breakfast','food'),
('air_conditioning','Air Conditioning','room'),
('generator','Backup Power','utilities')
on conflict(code) do nothing;
