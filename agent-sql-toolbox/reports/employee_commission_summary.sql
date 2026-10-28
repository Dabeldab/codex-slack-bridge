/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Calculate Commissions for all employees by date and location.sql"
and smaller employee sales/hour reports.
Purpose: read-only employee commission/hours/reimbursement summary.
*/

SET NOCOUNT ON;

DECLARE @StartDate DATETIME2(0) = '2025-01-01';
DECLARE @EndDateExclusive DATETIME2(0) = '2025-02-01';
DECLARE @LocationIdsCsv NVARCHAR(MAX) = NULL;
DECLARE @EmployeeId INT = NULL;

IF @EndDateExclusive <= @StartDate
BEGIN
    THROW 51000, 'Set a valid half-open date range.', 1;
END;

;WITH LocationFilter AS (
    SELECT TRY_CONVERT(INT, value) AS LocationID
    FROM STRING_SPLIT(COALESCE(@LocationIdsCsv, ''), ',')
    WHERE TRY_CONVERT(INT, value) IS NOT NULL
),
InvoiceCommission AS (
    SELECT
        ie.EmployeeID,
        inv.LocationID,
        COUNT(DISTINCT ie.InvoiceID) AS InvoiceCount,
        SUM(COALESCE(ie.AmountForComission, 0)) AS CommissionBase
    FROM dbo.Invoice_Employees AS ie
    JOIN dbo.Invoices AS inv ON inv.InvoiceID = ie.InvoiceID
    WHERE COALESCE(ie.AmountForComissionTimestamp, inv.[Timestamp]) >= @StartDate
      AND COALESCE(ie.AmountForComissionTimestamp, inv.[Timestamp]) < @EndDateExclusive
      AND (@EmployeeId IS NULL OR ie.EmployeeID = @EmployeeId)
      AND (
            @LocationIdsCsv IS NULL
            OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = inv.LocationID)
          )
    GROUP BY ie.EmployeeID, inv.LocationID
),
HoursWorked AS (
    SELECT
        eh.EmployeeID,
        eh.LocationID,
        SUM(COALESCE(eh.[Hours], 0)) AS HoursWorked
    FROM dbo.Employees_Hours AS eh
    WHERE eh.[Date] >= @StartDate
      AND eh.[Date] < @EndDateExclusive
      AND (@EmployeeId IS NULL OR eh.EmployeeID = @EmployeeId)
      AND (
            @LocationIdsCsv IS NULL
            OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = eh.LocationID)
          )
    GROUP BY eh.EmployeeID, eh.LocationID
),
Reimbursements AS (
    SELECT
        er.EmployeeID,
        er.LocationID,
        SUM(COALESCE(er.Amount, 0)) AS ReimbursementAmount
    FROM dbo.Employees_Reimbursements AS er
    WHERE er.[Timestamp] >= @StartDate
      AND er.[Timestamp] < @EndDateExclusive
      AND (@EmployeeId IS NULL OR er.EmployeeID = @EmployeeId)
      AND (
            @LocationIdsCsv IS NULL
            OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = er.LocationID)
          )
    GROUP BY er.EmployeeID, er.LocationID
),
Deductions AS (
    SELECT
        ed.EmployeeID,
        ed.LocationID,
        SUM(COALESCE(ed.Amount, 0)) AS DeductionAmount
    FROM dbo.Employees_Deductions AS ed
    WHERE ed.[Timestamp] >= @StartDate
      AND ed.[Timestamp] < @EndDateExclusive
      AND (@EmployeeId IS NULL OR ed.EmployeeID = @EmployeeId)
      AND (
            @LocationIdsCsv IS NULL
            OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = ed.LocationID)
          )
    GROUP BY ed.EmployeeID, ed.LocationID
),
EmployeeLocation AS (
    SELECT EmployeeID, LocationID FROM InvoiceCommission
    UNION
    SELECT EmployeeID, LocationID FROM HoursWorked
    UNION
    SELECT EmployeeID, LocationID FROM Reimbursements
    UNION
    SELECT EmployeeID, LocationID FROM Deductions
)
SELECT
    employee.EmployeeID,
    employee.EmployeeName,
    loc.LocationID,
    loc.LocationName,
    COALESCE(invoiceCommission.InvoiceCount, 0) AS InvoiceCount,
    COALESCE(invoiceCommission.CommissionBase, 0) AS CommissionBase,
    COALESCE(hoursWorked.HoursWorked, 0) AS HoursWorked,
    COALESCE(reimbursements.ReimbursementAmount, 0) AS ReimbursementAmount,
    COALESCE(deductions.DeductionAmount, 0) AS DeductionAmount,
    COALESCE(invoiceCommission.CommissionBase, 0)
      + COALESCE(reimbursements.ReimbursementAmount, 0)
      - COALESCE(deductions.DeductionAmount, 0) AS NetCommissionBeforeHourlyPay
FROM EmployeeLocation AS scope
JOIN dbo.Employees AS employee ON employee.EmployeeID = scope.EmployeeID
LEFT JOIN dbo.Locations AS loc ON loc.LocationID = scope.LocationID
LEFT JOIN InvoiceCommission AS invoiceCommission
    ON invoiceCommission.EmployeeID = scope.EmployeeID
   AND invoiceCommission.LocationID = scope.LocationID
LEFT JOIN HoursWorked AS hoursWorked
    ON hoursWorked.EmployeeID = scope.EmployeeID
   AND hoursWorked.LocationID = scope.LocationID
LEFT JOIN Reimbursements AS reimbursements
    ON reimbursements.EmployeeID = scope.EmployeeID
   AND reimbursements.LocationID = scope.LocationID
LEFT JOIN Deductions AS deductions
    ON deductions.EmployeeID = scope.EmployeeID
   AND deductions.LocationID = scope.LocationID
ORDER BY employee.EmployeeName, loc.LocationName
OPTION (RECOMPILE);
