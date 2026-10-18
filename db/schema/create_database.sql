-- Run once using psql against a maintenance database. Existing DBs are not reset.
\set ON_ERROR_STOP on
\if :{?database_name}
\else
  \set database_name sd6105_housing
\endif
CREATE DATABASE :"database_name" TEMPLATE template0 ENCODING 'UTF8';
\connect :database_name
\ir 001_schema.sql
