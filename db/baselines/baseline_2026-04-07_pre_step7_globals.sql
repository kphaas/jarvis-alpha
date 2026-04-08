--
-- PostgreSQL database cluster dump
--

\restrict vcrtYq7x4GAboanu8brNDBd0cdvdATj1hoMOBCvD1SIAefbdJUoLtSV3B089sMq

SET default_transaction_read_only = off;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

--
-- Roles
--

CREATE ROLE jarvis;
ALTER ROLE jarvis WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB LOGIN REPLICATION BYPASSRLS PASSWORD 'SCRAM-SHA-256$4096:bl9YhcbbIh4WUJglkSvHFg==$CRh1LIqy66mKWA0PJtHTV9bCj3y7M30kpl0WQX6gzuA=:ZRsv9MJIJ5yeJMaWJb4+ZqACnxnHSGq//wKN8//YU5M=';
CREATE ROLE jarvis_alpha_app;
ALTER ROLE jarvis_alpha_app WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOLOGIN NOREPLICATION NOBYPASSRLS;
CREATE ROLE jarvis_app;
ALTER ROLE jarvis_app WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB LOGIN NOREPLICATION NOBYPASSRLS PASSWORD 'SCRAM-SHA-256$4096:o85jbVhpWk9yIOGQju3GoQ==$4iRtm/6gYD4RKrhQ/lqeeskdMn/p3oa03puF2539dE8=:EQeuCCL+26ToGk0w0wB6YToplAbck3G3wqRuZ1Crtr0=';
CREATE ROLE jarvisbrain;
ALTER ROLE jarvisbrain WITH SUPERUSER INHERIT CREATEROLE CREATEDB LOGIN REPLICATION BYPASSRLS;

--
-- User Configurations
--


--
-- Role memberships
--

GRANT jarvis_alpha_app TO jarvisbrain WITH INHERIT TRUE GRANTED BY jarvisbrain;






\unrestrict vcrtYq7x4GAboanu8brNDBd0cdvdATj1hoMOBCvD1SIAefbdJUoLtSV3B089sMq

--
-- PostgreSQL database cluster dump complete
--

