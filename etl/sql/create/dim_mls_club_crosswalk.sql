DROP TABLE IF EXISTS dim_mls_club_crosswalk;

-- Every source spells MLS clubs differently. FBref writes 'Atlanta Utd' and "Vancouver
-- W'caps"; the MLSPA writes 'Atlanta United' and 'Vancouver Whitecaps'; and both have
-- renamed clubs over the years ('Montreal Impact' became 'CF Montréal'). This table
-- resolves any of those spellings to the one squad name the app displays, so a club
-- reads the same whichever pipeline the row arrived through.
--
-- Controlled by dv_clubs_cw.json: mls_squad_names lists the canonical names, and
-- fbref_squad_aliases / mlspa_club_aliases map each source's spellings onto them.
-- A NULL squad marks an MLSPA bucket that is not a club (MLS Pool, Retired, etc).
-- Keyed on (club_alias, source): the two feeds share some spellings while disagreeing
-- on others, so 'LAFC' has to exist once per source rather than once overall.
CREATE TABLE dim_mls_club_crosswalk (
        club_alias TEXT NOT NULL,
        source     TEXT NOT NULL, -- 'fbref' or 'mlspa': which feed uses this spelling
        squad      TEXT,          -- The canonical name; NULL when it is not a club
        PRIMARY KEY (club_alias, source)
);

CREATE INDEX IF NOT EXISTS idx_dim_mls_club_crosswalk__source
    ON dim_mls_club_crosswalk (source);
