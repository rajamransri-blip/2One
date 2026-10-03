-- Apply with Supabase SQL editor as a privileged database owner before starting the API.
-- The backend uses a private PostgreSQL connection; mobile apps only contact the backend.
-- Direct Supabase Auth access is additionally restricted by these RLS policies.
create table if not exists public.profiles (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  email varchar(320) not null unique, password_hash text, role varchar(8) not null check (role in ('parent','child')));
create table if not exists public.pair_codes (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  parent_id varchar(36) not null references public.profiles(id), code_hash varchar(64) not null unique,
  expires_at timestamptz not null, used_at timestamptz);
create table if not exists public.parent_child_links (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  parent_id varchar(36) not null references public.profiles(id), child_id varchar(36) not null references public.profiles(id),
  active boolean not null default true, unique(parent_id,child_id));
create index if not exists ix_links_parent on public.parent_child_links(parent_id);
create index if not exists ix_links_child on public.parent_child_links(child_id);
create table if not exists public.child_devices (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  child_id varchar(36) not null unique references public.profiles(id), name varchar(80) not null, sharing boolean not null default false);
create table if not exists public.device_status (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  child_id varchar(36) not null unique references public.profiles(id), online boolean not null default false,
  battery integer check (battery between 0 and 100), charging boolean, network varchar(32) not null default 'unknown',
  location_enabled boolean not null default false, notifications_enabled boolean not null default false,
  last_sync timestamptz not null default now());
create table if not exists public.locations (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  child_id varchar(36) not null references public.profiles(id), latitude double precision not null check (latitude between -90 and 90),
  longitude double precision not null check (longitude between -180 and 180), accuracy double precision not null check (accuracy >= 0),
  recorded_at timestamptz not null, battery integer, network varchar(32) not null default 'unknown');
create index if not exists ix_locations_child_recorded on public.locations(child_id,recorded_at desc);
create table if not exists public.geofences (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  parent_id varchar(36) not null references public.profiles(id), child_id varchar(36) not null references public.profiles(id),
  name varchar(80) not null, latitude double precision not null, longitude double precision not null, radius_m integer not null,
  notify_enter boolean not null default true, notify_exit boolean not null default true, inside boolean);
create index if not exists ix_geofences_child on public.geofences(child_id);
create table if not exists public.sos_events (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  child_id varchar(36) not null references public.profiles(id), latitude double precision, longitude double precision,
  battery integer, network varchar(32) not null default 'unknown', acknowledged_at timestamptz,
  acknowledged_by varchar(36) references public.profiles(id));
create index if not exists ix_sos_child on public.sos_events(child_id);
create table if not exists public.checkins (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  parent_id varchar(36) not null references public.profiles(id), child_id varchar(36) not null references public.profiles(id),
  deadline timestamptz not null, response varchar(16), responded_at timestamptz, reminder_sent boolean not null default false);
create index if not exists ix_checkins_child on public.checkins(child_id);
create table if not exists public.media_files (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  child_id varchar(36) not null references public.profiles(id), kind varchar(8) not null, mime varchar(40) not null,
  path text not null, size integer not null);
create index if not exists ix_media_child on public.media_files(child_id);
create table if not exists public.messages (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  child_id varchar(36) not null references public.profiles(id), sender_id varchar(36) not null references public.profiles(id),
  body varchar(2000) not null default '', media_id varchar(36) references public.media_files(id), delivered_at timestamptz,
  read_at timestamptz);
create index if not exists ix_messages_child on public.messages(child_id);
create table if not exists public.notifications (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  user_id varchar(36) not null references public.profiles(id), kind varchar(32) not null,
  child_id varchar(36) not null references public.profiles(id), detail varchar(200) not null, read_at timestamptz);
create index if not exists ix_notifications_user on public.notifications(user_id);
create table if not exists public.refresh_tokens (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  user_id varchar(36) not null references public.profiles(id), token_hash varchar(64) not null unique,
  kind varchar(12) not null default 'user' check (kind in ('user','service')),
  expires_at timestamptz not null, revoked_at timestamptz);
create index if not exists ix_refresh_user on public.refresh_tokens(user_id);
create table if not exists public.audit_events (
  id varchar(36) primary key, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  actor_id varchar(36) not null references public.profiles(id), action varchar(32) not null,
  child_id varchar(36) references public.profiles(id));
create index if not exists ix_audit_actor on public.audit_events(actor_id);

-- SECURITY DEFINER avoids recursive parent_child_links RLS checks; fixed search_path.
create or replace function public.is_linked(p_parent text, p_child text)
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists(select 1 from public.parent_child_links where parent_id=p_parent and child_id=p_child and active=true)
$$;
revoke all on function public.is_linked(text,text) from public;
grant execute on function public.is_linked(text,text) to authenticated;
create or replace function public.may_view_child(p_child text)
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select auth.uid()::text=p_child or public.is_linked(auth.uid()::text,p_child)
$$;
revoke all on function public.may_view_child(text) from public;
grant execute on function public.may_view_child(text) to authenticated;

alter table public.profiles enable row level security;
alter table public.pair_codes enable row level security;
alter table public.parent_child_links enable row level security;
alter table public.child_devices enable row level security;
alter table public.device_status enable row level security;
alter table public.locations enable row level security;
alter table public.geofences enable row level security;
alter table public.sos_events enable row level security;
alter table public.checkins enable row level security;
alter table public.messages enable row level security;
alter table public.media_files enable row level security;
alter table public.notifications enable row level security;
alter table public.refresh_tokens enable row level security;
alter table public.audit_events enable row level security;
-- Avoid any direct client write path: all writes are mediated by the backend, including pairing and safety events.
revoke all on all tables in schema public from anon, authenticated;
grant select on public.profiles, public.parent_child_links, public.child_devices, public.device_status,
  public.locations, public.geofences, public.sos_events, public.checkins, public.messages,
  public.media_files, public.notifications to authenticated;
-- The backend's private DATABASE_URL must use a privileged role to write these tables.
create policy profiles_read on public.profiles for select to authenticated using (
  id=auth.uid()::text or (role='child' and public.is_linked(auth.uid()::text,id))
  or (role='parent' and public.is_linked(id,auth.uid()::text)));
create policy links_read on public.parent_child_links for select to authenticated using (
  active=true and (parent_id=auth.uid()::text or child_id=auth.uid()::text));
create policy devices_read on public.child_devices for select to authenticated using (public.may_view_child(child_id));
create policy status_read on public.device_status for select to authenticated using (public.may_view_child(child_id));
create policy locations_read on public.locations for select to authenticated using (public.may_view_child(child_id));
create policy geofences_read on public.geofences for select to authenticated using (
  public.may_view_child(child_id) and public.is_linked(parent_id,child_id));
create policy sos_read on public.sos_events for select to authenticated using (public.may_view_child(child_id));
create policy checkins_read on public.checkins for select to authenticated using (
  public.may_view_child(child_id) and public.is_linked(parent_id,child_id));
create policy messages_read on public.messages for select to authenticated using (public.may_view_child(child_id));
create policy media_read on public.media_files for select to authenticated using (
  child_id=auth.uid()::text or (public.is_linked(auth.uid()::text,child_id)
  and exists(select 1 from public.messages m where m.media_id=media_files.id)));
create policy notifications_read on public.notifications for select to authenticated using (user_id=auth.uid()::text);
-- pair_codes, refresh_tokens and audit_events have no direct client policies or grants.
-- Schedule a daily database job (pg_cron or external job) to delete expired locations and
-- unshared media; also implement a separate retention policy for SOS/audit under local law.
