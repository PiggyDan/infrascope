-- Runs once, when the Postgres volume is first initialised.
-- A separate database so the test suite never touches development data.
CREATE DATABASE infrascope_test;
