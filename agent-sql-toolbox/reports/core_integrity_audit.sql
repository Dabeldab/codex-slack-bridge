/*
AgentChat/coding_agent 2026-07-09
Purpose: read-only integrity audit for common Nova POS support issues.

Run in the target POS_<Company_Username__c> database. Narrow @StartDate and
@EndDateExclusive when investigating invoice/report issues. This script uses
table variables and SELECT statements only; it does not modify database data.
*/

SET NOCOUNT ON;

DECLARE @StartDate DATETIME2(0) = DATEADD(DAY, -30, SYSUTCDATETIME());
DECLARE @EndDateExclusive DATETIME2(0) = DATEADD(DAY, 1, SYSUTCDATETIME());
DECLARE @InvoiceId INT = NULL;
DECLARE @IncludeAllHistory BIT = 0;

IF @IncludeAllHistory = 0
   AND (@StartDate IS NULL OR @EndDateExclusive IS NULL OR @EndDateExclusive <= @StartDate)
BEGIN
    THROW 51000, 'Set a valid half-open date range or set @IncludeAllHistory = 1.', 1;
END;

DECLARE @Audit TABLE (
    IssueType NVARCHAR(120) NOT NULL,
    Severity NVARCHAR(20) NOT NULL,
    IssueCount BIGINT NOT NULL,
    ExampleId NVARCHAR(120) NULL,
    Notes NVARCHAR(500) NOT NULL
);

DECLARE @Sql NVARCHAR(MAX);
DECLARE @Params NVARCHAR(MAX) = N'@StartDate DATETIME2(0), @EndDateExclusive DATETIME2(0), @InvoiceId INT, @IncludeAllHistory BIT';

IF OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Customers', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'CustomerID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'Timestamp') IS NOT NULL
   AND COL_LENGTH(N'dbo.Customers', N'CustomerID') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_CUSTOMER_NOT_FOUND'',
        N''high'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(inv.InvoiceID)),
        N''Invoices.CustomerID is populated but does not match Customers.CustomerID.''
    FROM dbo.Invoices AS inv
    LEFT JOIN dbo.Customers AS customer ON customer.CustomerID = inv.CustomerID
    WHERE inv.CustomerID IS NOT NULL
      AND customer.CustomerID IS NULL
      AND (@InvoiceId IS NULL OR inv.InvoiceID = @InvoiceId)
      AND (@IncludeAllHistory = 1 OR (inv.[Timestamp] >= @StartDate AND inv.[Timestamp] < @EndDateExclusive));';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Locations', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'LocationID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'Timestamp') IS NOT NULL
   AND COL_LENGTH(N'dbo.Locations', N'LocationID') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_LOCATION_NOT_FOUND'',
        N''high'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(inv.InvoiceID)),
        N''Invoices.LocationID is populated but does not match Locations.LocationID.''
    FROM dbo.Invoices AS inv
    LEFT JOIN dbo.Locations AS loc ON loc.LocationID = inv.LocationID
    WHERE inv.LocationID IS NOT NULL
      AND loc.LocationID IS NULL
      AND (@InvoiceId IS NULL OR inv.InvoiceID = @InvoiceId)
      AND (@IncludeAllHistory = 1 OR (inv.[Timestamp] >= @StartDate AND inv.[Timestamp] < @EndDateExclusive));';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoice_Products', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Products', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'Timestamp') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_PRODUCT_WITHOUT_INVOICE'',
        N''critical'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(ip.InvoiceID)),
        N''Invoice_Products row references an invoice header that does not exist.''
    FROM dbo.Invoice_Products AS ip
    LEFT JOIN dbo.Invoices AS inv ON inv.InvoiceID = ip.InvoiceID
    WHERE inv.InvoiceID IS NULL
      AND (@InvoiceId IS NULL OR ip.InvoiceID = @InvoiceId);';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoice_Products', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Products', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Products', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Products', N'ProductID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Products', N'ProductID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'Timestamp') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_PRODUCT_PRODUCT_NOT_FOUND'',
        N''high'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(ip.InvoiceID)),
        N''Invoice_Products.ProductID does not match Products.ProductID.''
    FROM dbo.Invoice_Products AS ip
    JOIN dbo.Invoices AS inv ON inv.InvoiceID = ip.InvoiceID
    LEFT JOIN dbo.Products AS product ON product.ProductID = ip.ProductID
    WHERE ip.ProductID IS NOT NULL
      AND product.ProductID IS NULL
      AND (@InvoiceId IS NULL OR ip.InvoiceID = @InvoiceId)
      AND (@IncludeAllHistory = 1 OR (inv.[Timestamp] >= @StartDate AND inv.[Timestamp] < @EndDateExclusive));';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoice_Payments', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Payments', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_PAYMENT_WITHOUT_INVOICE'',
        N''critical'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(payment.InvoiceID)),
        N''Invoice_Payments row references an invoice header that does not exist.''
    FROM dbo.Invoice_Payments AS payment
    LEFT JOIN dbo.Invoices AS inv ON inv.InvoiceID = payment.InvoiceID
    WHERE inv.InvoiceID IS NULL
      AND (@InvoiceId IS NULL OR payment.InvoiceID = @InvoiceId);';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoice_Payments', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Payments', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Payments', N'PaymentMethod') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'Timestamp') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_PAYMENT_METHOD_MISSING'',
        N''critical'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(payment.InvoiceID)),
        N''PaymentMethod is NULL, blank, or None. Nova invoice UI can fail or show blank payment details.''
    FROM dbo.Invoice_Payments AS payment
    JOIN dbo.Invoices AS inv ON inv.InvoiceID = payment.InvoiceID
    WHERE (payment.PaymentMethod IS NULL OR LTRIM(RTRIM(CONVERT(NVARCHAR(120), payment.PaymentMethod))) IN (N'''', N''None''))
      AND (@InvoiceId IS NULL OR payment.InvoiceID = @InvoiceId)
      AND (@IncludeAllHistory = 1 OR (inv.[Timestamp] >= @StartDate AND inv.[Timestamp] < @EndDateExclusive));';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoice_Payments', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Payments', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Payments', N'PaymentDetails') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'Timestamp') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_PAYMENT_DETAILS_MISSING'',
        N''high'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(payment.InvoiceID)),
        N''PaymentDetails is NULL or blank. Use a generic Nova-compatible placeholder when repairing.''
    FROM dbo.Invoice_Payments AS payment
    JOIN dbo.Invoices AS inv ON inv.InvoiceID = payment.InvoiceID
    WHERE (payment.PaymentDetails IS NULL OR LTRIM(RTRIM(CONVERT(NVARCHAR(400), payment.PaymentDetails))) = N'''')
      AND (@InvoiceId IS NULL OR payment.InvoiceID = @InvoiceId)
      AND (@IncludeAllHistory = 1 OR (inv.[Timestamp] >= @StartDate AND inv.[Timestamp] < @EndDateExclusive));';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoice_Employees', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Employees', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_EMPLOYEE_WITHOUT_INVOICE'',
        N''critical'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(ie.InvoiceID)),
        N''Invoice_Employees row references an invoice header that does not exist.''
    FROM dbo.Invoice_Employees AS ie
    LEFT JOIN dbo.Invoices AS inv ON inv.InvoiceID = ie.InvoiceID
    WHERE inv.InvoiceID IS NULL
      AND (@InvoiceId IS NULL OR ie.InvoiceID = @InvoiceId);';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Invoice_Employees', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Employees', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Employees', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoice_Employees', N'EmployeeID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Employees', N'EmployeeID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'Timestamp') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''INVOICE_EMPLOYEE_NOT_FOUND'',
        N''high'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(ie.InvoiceID)),
        N''Invoice_Employees.EmployeeID does not match Employees.EmployeeID.''
    FROM dbo.Invoice_Employees AS ie
    JOIN dbo.Invoices AS inv ON inv.InvoiceID = ie.InvoiceID
    LEFT JOIN dbo.Employees AS employee ON employee.EmployeeID = ie.EmployeeID
    WHERE ie.EmployeeID IS NOT NULL
      AND employee.EmployeeID IS NULL
      AND (@InvoiceId IS NULL OR ie.InvoiceID = @InvoiceId)
      AND (@IncludeAllHistory = 1 OR (inv.[Timestamp] >= @StartDate AND inv.[Timestamp] < @EndDateExclusive));';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Inventory', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Products', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Inventory', N'ProductID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Products', N'ProductID') IS NOT NULL
BEGIN
    INSERT INTO @Audit
    SELECT
        N'INVENTORY_PRODUCT_NOT_FOUND',
        N'high',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(inventory.ProductID)),
        N'Inventory.ProductID does not match Products.ProductID.'
    FROM dbo.Inventory AS inventory
    LEFT JOIN dbo.Products AS product ON product.ProductID = inventory.ProductID
    WHERE inventory.ProductID IS NOT NULL
      AND product.ProductID IS NULL;
END;

IF OBJECT_ID(N'dbo.Inventory', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Locations', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Inventory', N'LocationID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Locations', N'LocationID') IS NOT NULL
BEGIN
    INSERT INTO @Audit
    SELECT
        N'INVENTORY_LOCATION_NOT_FOUND',
        N'high',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(inventory.LocationID)),
        N'Inventory.LocationID does not match Locations.LocationID.'
    FROM dbo.Inventory AS inventory
    LEFT JOIN dbo.Locations AS loc ON loc.LocationID = inventory.LocationID
    WHERE inventory.LocationID IS NOT NULL
      AND loc.LocationID IS NULL;
END;

IF OBJECT_ID(N'dbo.Inventory', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Inventory', N'ProductID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Inventory', N'LocationID') IS NOT NULL
BEGIN
    INSERT INTO @Audit
    SELECT
        N'DUPLICATE_INVENTORY_PRODUCT_LOCATION',
        N'medium',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(CONCAT(duplicateRows.LocationID, N'/', duplicateRows.ProductID))),
        N'Multiple Inventory rows exist for the same LocationID/ProductID.'
    FROM (
        SELECT LocationID, ProductID
        FROM dbo.Inventory
        GROUP BY LocationID, ProductID
        HAVING COUNT_BIG(*) > 1
    ) AS duplicateRows;
END;

IF OBJECT_ID(N'dbo.Products', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Products_Categories', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Products', N'ProductID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Products', N'Product_CategoryID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Products_Categories', N'Products_CategoryID') IS NOT NULL
BEGIN
    INSERT INTO @Audit
    SELECT
        N'PRODUCT_CATEGORY_NOT_FOUND',
        N'medium',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(product.ProductID)),
        N'Products.Product_CategoryID does not match Products_Categories.Products_CategoryID.'
    FROM dbo.Products AS product
    LEFT JOIN dbo.Products_Categories AS category
        ON category.Products_CategoryID = product.Product_CategoryID
    WHERE product.Product_CategoryID IS NOT NULL
      AND category.Products_CategoryID IS NULL;
END;

IF OBJECT_ID(N'dbo.Appointments', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Customers', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Appointments', N'CustomerID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Appointments', N'Start') IS NOT NULL
   AND COL_LENGTH(N'dbo.Customers', N'CustomerID') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''APPOINTMENT_CUSTOMER_NOT_FOUND'',
        N''medium'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(ap.Id)),
        N''Appointments.CustomerID does not match Customers.CustomerID.''
    FROM dbo.Appointments AS ap
    LEFT JOIN dbo.Customers AS customer ON customer.CustomerID = ap.CustomerID
    WHERE ap.CustomerID IS NOT NULL
      AND customer.CustomerID IS NULL
      AND (@IncludeAllHistory = 1 OR (ap.[Start] >= @StartDate AND ap.[Start] < @EndDateExclusive));';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Refunds', N'U') IS NOT NULL
   AND OBJECT_ID(N'dbo.Invoices', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Refunds', N'InvoiceID') IS NOT NULL
   AND COL_LENGTH(N'dbo.Invoices', N'InvoiceID') IS NOT NULL
BEGIN
    SET @Sql = N'
    SELECT
        N''REFUND_INVOICE_NOT_FOUND'',
        N''high'',
        COUNT_BIG(*),
        CONVERT(NVARCHAR(120), MIN(refund.InvoiceID)),
        N''Refunds.InvoiceID does not match Invoices.InvoiceID.''
    FROM dbo.Refunds AS refund
    LEFT JOIN dbo.Invoices AS inv ON inv.InvoiceID = refund.InvoiceID
    WHERE refund.InvoiceID IS NOT NULL
      AND inv.InvoiceID IS NULL
      AND (@InvoiceId IS NULL OR refund.InvoiceID = @InvoiceId);';
    INSERT INTO @Audit EXEC sys.sp_executesql @Sql, @Params, @StartDate = @StartDate, @EndDateExclusive = @EndDateExclusive, @InvoiceId = @InvoiceId, @IncludeAllHistory = @IncludeAllHistory;
END;

IF OBJECT_ID(N'dbo.Refunds_Payments', N'U') IS NOT NULL
   AND COL_LENGTH(N'dbo.Refunds_Payments', N'PaymentMethod') IS NOT NULL
BEGIN
    INSERT INTO @Audit
    SELECT
        N'REFUND_PAYMENT_METHOD_MISSING',
        N'high',
        COUNT_BIG(*),
        NULL,
        N'Refunds_Payments.PaymentMethod is NULL, blank, or None.'
    FROM dbo.Refunds_Payments AS payment
    WHERE payment.PaymentMethod IS NULL
       OR LTRIM(RTRIM(CONVERT(NVARCHAR(120), payment.PaymentMethod))) IN (N'', N'None');
END;

SELECT
    DB_NAME() AS DatabaseName,
    @StartDate AS StartDate,
    @EndDateExclusive AS EndDateExclusive,
    @InvoiceId AS InvoiceId,
    @IncludeAllHistory AS IncludeAllHistory;

SELECT
    IssueType,
    Severity,
    IssueCount,
    ExampleId,
    Notes
FROM @Audit
WHERE IssueCount > 0
ORDER BY
    CASE Severity
        WHEN N'critical' THEN 1
        WHEN N'high' THEN 2
        WHEN N'medium' THEN 3
        ELSE 4
    END,
    IssueType;

IF NOT EXISTS (SELECT 1 FROM @Audit WHERE IssueCount > 0)
BEGIN
    SELECT N'NO_ISSUES_FOUND_FOR_CONFIGURED_SCOPE' AS AuditStatus;
END;
