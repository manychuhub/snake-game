create table shiftbridge_web.ai_notifications (
    id text primary key,
    sender_id bigint not null references shiftbridge_web.web_users(id),
    recipient_id bigint not null references shiftbridge_web.web_users(id),
    sender text not null,
    ticket_no text not null,
    created_at text not null
);

create index ai_notifications_sender on shiftbridge_web.ai_notifications(sender_id, created_at);
create index ai_notifications_recipient on shiftbridge_web.ai_notifications(recipient_id, created_at);

alter table shiftbridge_web.ai_notifications enable row level security;
alter table shiftbridge_web.ai_notifications force row level security;

create policy read_own_notifications on shiftbridge_web.ai_notifications for select to shift_bridge_web
    using (nullif(current_setting('shift_bridge.account_id', true), '')::bigint in (sender_id, recipient_id));

create policy send_own_notifications on shiftbridge_web.ai_notifications for insert to shift_bridge_web
    with check (sender_id = nullif(current_setting('shift_bridge.account_id', true), '')::bigint);

grant select, insert on shiftbridge_web.ai_notifications to shift_bridge_web;
