create table shiftbridge_web.ai_tool_confirmations (
    workspace_id bigint not null default nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint,
    id text not null,
    actor_id bigint not null,
    tool text not null,
    target_id text,
    payload text not null,
    request_message text not null,
    expires_at bigint not null,
    response text,
    primary key (workspace_id, id)
);

alter table shiftbridge_web.ai_tool_confirmations enable row level security;
alter table shiftbridge_web.ai_tool_confirmations force row level security;
create policy own_tool_confirmations on shiftbridge_web.ai_tool_confirmations to shift_bridge_web
    using (workspace_id = nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint
        and actor_id = nullif(current_setting('shift_bridge.account_id', true), '')::bigint)
    with check (workspace_id = nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint
        and actor_id = nullif(current_setting('shift_bridge.account_id', true), '')::bigint);
grant select, insert on shiftbridge_web.ai_tool_confirmations to shift_bridge_web;
grant update (response) on shiftbridge_web.ai_tool_confirmations to shift_bridge_web;

create table shiftbridge_web.dco_work_requests (
    workspace_id bigint not null default nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint,
    id text not null,
    kind text not null,
    item_id text not null,
    quantity integer not null check (quantity >= 0),
    details text not null,
    primary key (workspace_id, id)
);

create index dco_work_requests_item on shiftbridge_web.dco_work_requests (workspace_id, kind, item_id);
alter table shiftbridge_web.dco_work_requests enable row level security;
alter table shiftbridge_web.dco_work_requests force row level security;
create policy own_dco_workspace on shiftbridge_web.dco_work_requests to shift_bridge_web
    using (workspace_id = nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint)
    with check (workspace_id = nullif(current_setting('shift_bridge.workspace_id', true), '')::bigint);
grant select, insert on shiftbridge_web.dco_work_requests to shift_bridge_web;
