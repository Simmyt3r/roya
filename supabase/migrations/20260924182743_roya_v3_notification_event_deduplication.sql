create unique index if not exists uq_notifications_reservation_event_recipient
  on public.notifications(channel,event_type,reservation_id,recipient)
  where reservation_id is not null;
