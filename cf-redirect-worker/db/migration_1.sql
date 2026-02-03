create schema if not exists tracking;
create table if not exists tracking.cloudflare_logs (id serial primary key, created_at timestamptz default current_timestamp, data jsonb);
