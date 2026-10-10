-- Applies the salaries matched in stg_MLSPA_mls_players_salaries to a season's
-- Schmetzer Scores, then ranks players by value. {salary_basis} is the compensation
-- column the ranking divides by, from data_vars.json. The per-dollar figure itself is
-- not stored -- the app derives it from the score and salary columns.

-- Clear any salary figures from a previous run so removed matches do not linger
UPDATE "schmetzer_scores_{year}"
SET base_salary = NULL,
    guaranteed_comp = NULL,
    salary_match_tier = NULL,
    schmetzer_value_rk = NULL;

UPDATE "schmetzer_scores_{year}"
SET base_salary = (
        SELECT salaries.base_salary
        FROM stg_MLSPA_mls_players_salaries salaries
        WHERE salaries.schmetzer_id = "schmetzer_scores_{year}".id
    ),
    guaranteed_comp = (
        SELECT salaries.guaranteed_comp
        FROM stg_MLSPA_mls_players_salaries salaries
        WHERE salaries.schmetzer_id = "schmetzer_scores_{year}".id
    ),
    salary_match_tier = (
        SELECT salaries.salary_match_tier
        FROM stg_MLSPA_mls_players_salaries salaries
        WHERE salaries.schmetzer_id = "schmetzer_scores_{year}".id
    )
WHERE EXISTS (
    SELECT 1
    FROM stg_MLSPA_mls_players_salaries salaries
    WHERE salaries.schmetzer_id = "schmetzer_scores_{year}".id
);

-- Rank by Schmetzer Score per dollar of compensation: how much contested possession
-- a club bought with the money it committed to the player. Only players past the
-- minutes floor are ranked; below it a single substitute appearance on a
-- league-minimum contract would otherwise top the table on a handful of duels.
WITH ranked AS (
    SELECT
        rowid AS original_rowid,
        RANK() OVER (ORDER BY schmetzer_score / {salary_basis} DESC) AS rk
    FROM "schmetzer_scores_{year}"
    WHERE {salary_basis} > 0
      AND schmetzer_score IS NOT NULL
      AND nineties >= {min_nineties}
)
UPDATE "schmetzer_scores_{year}"
SET schmetzer_value_rk = (
    SELECT rk FROM ranked WHERE ranked.original_rowid = "schmetzer_scores_{year}".rowid
);
