/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Appointment with Duration.sql".
Purpose: read-only appointment duration export for the current POS database.
*/

SET NOCOUNT ON;

DECLARE @StartDate DATETIME2(0) = DATEADD(DAY, -30, SYSUTCDATETIME());
DECLARE @EndDateExclusive DATETIME2(0) = DATEADD(DAY, 1, SYSUTCDATETIME());
DECLARE @LocationIdsCsv NVARCHAR(MAX) = NULL;
DECLARE @EmployeeId INT = NULL;
DECLARE @CustomerId INT = NULL;

;WITH LocationFilter AS (
    SELECT TRY_CONVERT(INT, value) AS LocationID
    FROM STRING_SPLIT(COALESCE(@LocationIdsCsv, ''), ',')
    WHERE TRY_CONVERT(INT, value) IS NOT NULL
)
SELECT
    ap.Id AS AppointmentID,
    ap.[Start] AS StartTime,
    ap.[End] AS EndTime,
    DATEDIFF(MINUTE, ap.[Start], ap.[End]) AS DurationMinutes,
    CONCAT(
        DATEDIFF(MINUTE, ap.[Start], ap.[End]) / 1440, ' day ',
        (DATEDIFF(MINUTE, ap.[Start], ap.[End]) % 1440) / 60, ' hr ',
        DATEDIFF(MINUTE, ap.[Start], ap.[End]) % 60, ' min'
    ) AS DurationLabel,
    customer.CustomerID,
    CONCAT(customer.CustomerFirstName, ' ', customer.CustomerLastName) AS CustomerName,
    ap.[Description],
    employee.EmployeeID,
    employee.EmployeeName,
    loc.LocationID,
    loc.LocationName
FROM dbo.Appointments AS ap
LEFT JOIN dbo.Locations AS loc ON loc.LocationID = ap.LocationID
LEFT JOIN dbo.Customers AS customer ON customer.CustomerID = ap.CustomerID
LEFT JOIN dbo.Employees AS employee ON employee.EmployeeID = ap.EmployeeID
WHERE ap.[Start] >= @StartDate
  AND ap.[Start] < @EndDateExclusive
  AND (@EmployeeId IS NULL OR ap.EmployeeID = @EmployeeId)
  AND (@CustomerId IS NULL OR ap.CustomerID = @CustomerId)
  AND (
        @LocationIdsCsv IS NULL
        OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = ap.LocationID)
      )
ORDER BY ap.[Start] DESC
OPTION (RECOMPILE);
