create table shiftbridge_web.ai_confirmations (
    workspace_id bigint not null default nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint,
    id text not null,
    actor_id bigint not null,
    log_id bigint not null,
    ticket_no text,
    device_id text,
    expected_status text,
    new_status text not null,
    response text,
    primary key (workspace_id, id)
);

alter table shiftbridge_web.ai_confirmations enable row level security;
alter table shiftbridge_web.ai_confirmations force row level security;
create policy own_confirmations on shiftbridge_web.ai_confirmations to shift_bridge_web
    using (workspace_id = nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint
        and actor_id = nullif(current_setting('shift_bridge.account_id', true), '')::bigint)
    with check (workspace_id = nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint
        and actor_id = nullif(current_setting('shift_bridge.account_id', true), '')::bigint);

grant select, insert on shiftbridge_web.ai_confirmations to shift_bridge_web;
grant update (response) on shiftbridge_web.ai_confirmations to shift_bridge_web;
