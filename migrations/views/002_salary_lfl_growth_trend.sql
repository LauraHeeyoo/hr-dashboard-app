-- ============================================================================
-- mcp.fn_salary_lfl_growth_trend(@start_date, @end_date, @granularity)
--
-- "Like-for-like" (LFL) YoY salary growth trend — one row per included
-- snapshot date in the range. For each date, finds each employee's salary
-- 12 months earlier (retained-cohort comparison: only employees present at
-- both dates count), and averages the per-employee growth rate.
--
-- This was one of the genuinely complex DAX measures in the old model
-- (ARCHITECTURE.md §1.2) — a retained-cohort self-join, not a plain
-- aggregate. Two variants, matching the old area chart's two series:
--   - LFL_Growth_Pct: all retained employees
--   - LFL_Growth_SameRoleContract_Pct: further restricted to employees
--     whose role AND contract type are unchanged between the two dates
--     (the "apples to apples" stricter comparison)
--
-- @granularity ('month' | 'year') controls which dates get their own row:
-- 'month' (default, unchanged behavior) includes every available snapshot
-- date; 'year' includes only the latest available snapshot date per
-- calendar year — the drill-out view (salaris.html — Laura: "groter
-- drillen naar jaar" should be a real recomputed YoY between year-anchors,
-- not just picking a pre-computed monthly point). The 12-month lookback
-- itself never changes — only which dates count as a "current" anchor
-- does, so this is a real re-aggregation, not a display-only subsample.
-- Deliberately picks the *latest* date per year rather than assuming
-- December, since it must keep working if the underlying simulation is
-- ever re-run with a different date range.
--
-- Note: aliased as CurrentSnapshotDate/PriorSnapshotDate, not
-- Current_Date/Prior_Date — the latter hit a SQL Server parser error
-- ("Incorrect syntax near the keyword 'Current_Date'"), since CURRENT_DATE
-- is a reserved word in SQL Server's parser even though T-SQL itself uses
-- GETDATE() instead of implementing it.
-- ============================================================================
CREATE OR ALTER FUNCTION mcp.fn_salary_lfl_growth_trend (
    @start_date DATE,
    @end_date DATE,
    @granularity NVARCHAR(10) = 'month'
)
RETURNS TABLE
AS
RETURN
(
    WITH distinct_dates AS (
        SELECT DISTINCT Snapshot_Date
        FROM dbo.fact_workforce_snapshot
        WHERE Snapshot_Date BETWEEN @start_date AND @end_date
    ),
    snapshot_dates AS (
        SELECT Snapshot_Date FROM distinct_dates WHERE @granularity <> 'year'
        UNION
        SELECT Snapshot_Date
        FROM (
            SELECT
                Snapshot_Date,
                ROW_NUMBER() OVER (PARTITION BY YEAR(Snapshot_Date) ORDER BY Snapshot_Date DESC) AS rn
            FROM distinct_dates
        ) AS ranked
        WHERE @granularity = 'year' AND rn = 1
    ),
    prior_dates AS (
        -- for each snapshot date, the latest available snapshot date that's
        -- <= (that date minus 12 months) — "the same employees, a year ago"
        SELECT
            sd.Snapshot_Date AS CurrentSnapshotDate,
            (
                SELECT MAX(Snapshot_Date)
                FROM dbo.fact_workforce_snapshot
                WHERE Snapshot_Date <= DATEADD(MONTH, -12, sd.Snapshot_Date)
            ) AS PriorSnapshotDate
        FROM snapshot_dates AS sd
    ),
    paired AS (
        SELECT
            pd.CurrentSnapshotDate,
            cur.Employee_Key,
            cur.Salaris AS Current_Salaris,
            prior.Salaris AS Prior_Salaris,
            cur.Role_Key AS Current_Role_Key,
            prior.Role_Key AS Prior_Role_Key,
            cur.Contracttype AS Current_Contracttype,
            prior.Contracttype AS Prior_Contracttype
        FROM prior_dates AS pd
        INNER JOIN dbo.fact_workforce_snapshot AS cur
            ON cur.Snapshot_Date = pd.CurrentSnapshotDate
        INNER JOIN dbo.fact_workforce_snapshot AS prior
            ON prior.Snapshot_Date = pd.PriorSnapshotDate
           AND prior.Employee_Key = cur.Employee_Key
        WHERE pd.PriorSnapshotDate IS NOT NULL
          AND prior.Salaris > 0
    )
    SELECT
        CurrentSnapshotDate AS Snapshot_Date,
        AVG(CAST(Current_Salaris - Prior_Salaris AS DECIMAL(18, 4)) / Prior_Salaris) AS LFL_Growth_Pct,
        AVG(CASE
                WHEN Current_Role_Key = Prior_Role_Key AND Current_Contracttype = Prior_Contracttype
                THEN CAST(Current_Salaris - Prior_Salaris AS DECIMAL(18, 4)) / Prior_Salaris
            END) AS LFL_Growth_SameRoleContract_Pct,
        COUNT(*) AS Retained_Employee_Count
    FROM paired
    GROUP BY CurrentSnapshotDate
);
GO
