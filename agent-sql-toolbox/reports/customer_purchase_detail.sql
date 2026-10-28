/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Customers, how much they paid.sql" in the local SSMS folders.
Purpose: read-only customer/product/payment purchase export for the current POS database.
*/

SET NOCOUNT ON;

DECLARE @StartDate DATETIME2(0) = '2025-01-01';
DECLARE @EndDateExclusive DATETIME2(0) = '2025-02-01';
DECLARE @LocationIdsCsv NVARCHAR(MAX) = NULL; -- example: '1,2,3'
DECLARE @CustomerId INT = NULL;
DECLARE @InvoiceId INT = NULL;

IF @StartDate IS NULL OR @EndDateExclusive IS NULL OR @EndDateExclusive <= @StartDate
BEGIN
    THROW 51000, 'Set a valid half-open date range: @StartDate <= timestamp < @EndDateExclusive.', 1;
END;

;WITH LocationFilter AS (
    SELECT TRY_CONVERT(INT, value) AS LocationID
    FROM STRING_SPLIT(COALESCE(@LocationIdsCsv, ''), ',')
    WHERE TRY_CONVERT(INT, value) IS NOT NULL
),
PaymentRollup AS (
    SELECT
        ip.InvoiceID,
        STRING_AGG(CONVERT(NVARCHAR(80), ip.PaymentMethod), ', ') AS PaymentMethods,
        STRING_AGG(CONVERT(NVARCHAR(200), ip.PaymentDetails), ' | ') AS PaymentDetails,
        SUM(COALESCE(ip.Amount, 0)) AS PaymentAmount
    FROM dbo.Invoice_Payments AS ip
    GROUP BY ip.InvoiceID
)
SELECT
    inv.InvoiceID,
    inv.[Timestamp] AS InvoiceTimestamp,
    loc.LocationID,
    loc.LocationName,
    crm.CustomerID,
    crm.CustomerFirstName,
    crm.CustomerLastName,
    crm.CustomerLandLine,
    crm.CustomerMobile,
    crm.CustomerEmail,
    p.ProductID,
    p.ProductName,
    p.ProductDescription,
    p.BarcodeNumber,
    p.BarcodeNumber2,
    p.SKU,
    invoiceProduct.Quantity,
    invoiceProduct.ProductPrice,
    invoiceProduct.ProductDiscount,
    invoiceProduct.ProductPrice - COALESCE(invoiceProduct.ProductDiscount, 0) AS NetProductPrice,
    invoiceProduct.ProductTax,
    inv.Total AS InvoiceTotal,
    payments.PaymentMethods,
    payments.PaymentDetails,
    payments.PaymentAmount,
    emp.EmployeeName,
    invoiceEmployee.AmountForComission,
    region.RegionName,
    crm.DateAdded AS CustomerAddedDate
FROM dbo.Invoices AS inv
LEFT JOIN dbo.Customers AS crm ON crm.CustomerID = inv.CustomerID
LEFT JOIN dbo.Locations AS loc ON loc.LocationID = inv.LocationID
LEFT JOIN dbo.Regions AS region ON region.RegionID = loc.RegionID
LEFT JOIN dbo.Invoice_Products AS invoiceProduct ON invoiceProduct.InvoiceID = inv.InvoiceID
LEFT JOIN dbo.Products AS p ON p.ProductID = invoiceProduct.ProductID
LEFT JOIN dbo.Invoice_Employees AS invoiceEmployee ON invoiceEmployee.InvoiceID = inv.InvoiceID
LEFT JOIN dbo.Employees AS emp ON emp.EmployeeID = invoiceEmployee.EmployeeID
LEFT JOIN PaymentRollup AS payments ON payments.InvoiceID = inv.InvoiceID
WHERE inv.[Timestamp] >= @StartDate
  AND inv.[Timestamp] < @EndDateExclusive
  AND (@CustomerId IS NULL OR inv.CustomerID = @CustomerId)
  AND (@InvoiceId IS NULL OR inv.InvoiceID = @InvoiceId)
  AND (
        @LocationIdsCsv IS NULL
        OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = inv.LocationID)
      )
ORDER BY loc.LocationName, inv.InvoiceID, p.ProductName
OPTION (RECOMPILE);
