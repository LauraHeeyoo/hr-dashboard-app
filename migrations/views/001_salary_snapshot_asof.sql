-- ============================================================================
-- mcp.fn_workforce_snapshot_asof(@as_of_date, @afdeling, @functie, @manager,
--                                 @opleidingsniveau, @salaris_categorie, @bron)
--
-- The reusable "op peildatum" (as-of) pattern: one row per employee, their
-- latest fact_workforce_snapshot row with Snapshot_Date <= @as_of_date.
-- This is the single most important pattern from the old Power BI model
-- (ARCHITECTURE.md §1.2/§7) — nearly every point-in-time measure on the
-- Salaris page (median salary, benchmark ratio, %-under-benchmark, the
-- histogram, the department/category breakdown) derives from this one
-- lookup. It's an inline table-valued FUNCTION, not a plain VIEW, because
-- it needs to accept parameters — a plain view can't.
--
-- All six filter parameters default to NULL ("no filter") and use the
-- standard `@param IS NULL OR column = @param` pattern — filtering happens
-- in SQL, not by fetching everything and filtering in Python (§7.3), and
-- every value is a bound parameter, never a string built from user input
-- (§7.4). These map directly to the Salaris page's filter rail.
--
-- Salaris_Categorie is the canonical definition from ARCHITECTURE.md §14.2:
-- dim_salary_band's range-based intent, via a real BETWEEN comparison
-- (handling the open-ended top band, Maximum_Salaris IS NULL = "and above"),
-- not the old model's fragile exact-value matching.
--
-- Performance_Bin: fact_workforce_snapshot.Performance_Score is entirely
-- NULL in this database — verified, not assumed — the populated column is
-- Prestatie_Score (2.39-5.0 range, checked). Bucketed here into 0.5-wide
-- bins, matching the old dim_employee[Performance Bin] DAX column (favoring
-- that definition over fact_workforce_snapshot's own 1.0-wide "Performance
-- band", the same "prefer the person-level definition" reasoning as the
-- tenure conflict in §14.1) — a minor bucketing default, not a headline
-- business metric like salary category, so not logged as its own §14 entry.
--
-- Cross-visual interactivity (clicking a bar segment) is a client-side
-- highlight, not a server-side filter — it fades unrelated marks in other
-- charts using data already sent to the browser (salaris.html), rather
-- than adding more parameters here. An earlier version of this function
-- did add three extra filter params for a click-as-filter interaction;
-- that turned out not to match how Power BI's own cross-highlight actually
-- behaves (data stays visible, just dimmed, instead of disappearing), so
-- it was reverted.
-- ============================================================================
CREATE OR ALTER FUNCTION mcp.fn_workforce_snapshot_asof (
    @as_of_date DATE,
    @afdeling NVARCHAR(100) = NULL,
    @functie NVARCHAR(100) = NULL,
    @manager NVARCHAR(101) = NULL,
    @opleidingsniveau NVARCHAR(20) = NULL,
    @salaris_categorie NVARCHAR(100) = NULL,
    @bron NVARCHAR(100) = NULL
)
RETURNS TABLE
AS
RETURN
(
    SELECT
        s.Employee_Key,
        s.Snapshot_Date,
        s.Department_Key,
        d.Afdeling_Naam,
        s.Role_Key,
        r.Functie_Naam,
        s.Manager_Key,
        m.Voornaam + ' ' + m.Achternaam AS Manager_Naam,
        s.Contracttype,
        s.Contracturen,
        s.FTE,
        s.Salaris,
        s.Benchmark_Salaris,
        s.Benchmark_Verschil,
        s.Benchmark_Status,
        CASE WHEN s.Benchmark_Salaris > 0
             THEN CAST(s.Salaris AS DECIMAL(18, 4)) / s.Benchmark_Salaris
             ELSE NULL
        END AS Benchmark_Ratio,
        sb.SalaryBand_Key,
        sb.Salarisband_Naam AS Salaris_Categorie,
        s.Dienstjaren,
        s.Prestatie_Score,
        CASE
            WHEN s.Prestatie_Score IS NULL THEN NULL
            WHEN s.Prestatie_Score < 3.0 THEN '< 3.0'
            WHEN s.Prestatie_Score < 3.5 THEN '3.0 - 3.5'
            WHEN s.Prestatie_Score < 4.0 THEN '3.5 - 4.0'
            WHEN s.Prestatie_Score < 4.5 THEN '4.0 - 4.5'
            ELSE '4.5 - 5.0'
        END AS Performance_Bin,
        s.SatisfactionBand_Key,
        satb.Tevredenheidsband_Naam,
        e.Geslacht,
        edu.Opleidingsniveau,
        hs.Bron_Naam
    FROM dbo.fact_workforce_snapshot AS s
    INNER JOIN (
        -- the actual "as-of" resolution: latest snapshot per employee on/before the date
        SELECT Employee_Key, MAX(Snapshot_Date) AS Snapshot_Date
        FROM dbo.fact_workforce_snapshot
        WHERE Snapshot_Date <= @as_of_date
        GROUP BY Employee_Key
    ) AS latest
        ON latest.Employee_Key = s.Employee_Key
       AND latest.Snapshot_Date = s.Snapshot_Date
    LEFT JOIN dbo.dim_department AS d ON d.Department_Key = s.Department_Key
    LEFT JOIN dbo.dim_role AS r ON r.Role_Key = s.Role_Key
    LEFT JOIN dbo.dim_manager AS m ON m.Manager_Key = s.Manager_Key
    LEFT JOIN dbo.dim_salary_band AS sb
        ON s.Salaris >= sb.Minimum_Salaris
       AND (s.Salaris <= sb.Maximum_Salaris OR sb.Maximum_Salaris IS NULL)
    LEFT JOIN dbo.dim_satisfaction_band AS satb ON satb.SatisfactionBand_Key = s.SatisfactionBand_Key
    LEFT JOIN dbo.dim_employee AS e ON e.Employee_Key = s.Employee_Key
    LEFT JOIN dbo.dim_education AS edu ON edu.Education_Key = s.Education_Key
    LEFT JOIN dbo.dim_hire_source AS hs ON hs.HireSource_Key = s.HireSource_Key
    WHERE (@afdeling IS NULL OR d.Afdeling_Naam = @afdeling)
      AND (@functie IS NULL OR r.Functie_Naam = @functie)
      AND (@manager IS NULL OR (m.Voornaam + ' ' + m.Achternaam) = @manager)
      AND (@opleidingsniveau IS NULL OR edu.Opleidingsniveau = @opleidingsniveau)
      AND (@salaris_categorie IS NULL OR sb.Salarisband_Naam = @salaris_categorie)
      AND (@bron IS NULL OR hs.Bron_Naam = @bron)
);
GO
