/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "database-copy-script.sql", "database-merge-script.sql",
and "Merge Multiple Accounts, Full copy.sql".
Purpose: read-only source/target readiness checks before any account clone/copy work.
*/

SET NOCOUNT ON;

DECLARE @SourceDB SYSNAME = N'POS_SOURCE_ACCOUNT';
DECLARE @TargetDB SYSNAME = DB_NAME();

IF DB_ID(@SourceDB) IS NULL
BEGIN
    THROW 51000, 'Source database was not found on this SQL Server.', 1;
END;

IF DB_ID(@TargetDB) IS NULL
BEGIN
    THROW 51000, 'Target database was not found on this SQL Server.', 1;
END;

DECLARE @Sql NVARCHAR(MAX) = N'
SELECT
    SourceDB = @SourceDB,
    TargetDB = @TargetDB,
    TableName,
    SourceRows,
    TargetRows,
    SourceIdentityMax,
    TargetIdentityMax
FROM (
    SELECT ''Products'' AS TableName,
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products) AS SourceRows,
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Products) AS TargetRows,
        (SELECT MAX(ProductID) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products) AS SourceIdentityMax,
        (SELECT MAX(ProductID) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Products) AS TargetIdentityMax
    UNION ALL SELECT ''Products_Categories'',
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products_Categories),
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Products_Categories),
        (SELECT MAX(Products_CategoryID) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products_Categories),
        (SELECT MAX(Products_CategoryID) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Products_Categories)
    UNION ALL SELECT ''Inventory'',
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Inventory),
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Inventory),
        (SELECT MAX(InventoryID) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Inventory),
        (SELECT MAX(InventoryID) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Inventory)
    UNION ALL SELECT ''Locations'',
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Locations),
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Locations),
        (SELECT MAX(LocationID) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Locations),
        (SELECT MAX(LocationID) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Locations)
    UNION ALL SELECT ''Customers'',
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Customers),
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Customers),
        (SELECT MAX(CustomerID) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Customers),
        (SELECT MAX(CustomerID) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Customers)
    UNION ALL SELECT ''Invoices'',
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Invoices),
        (SELECT COUNT_BIG(*) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Invoices),
        (SELECT MAX(InvoiceID) FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Invoices),
        (SELECT MAX(InvoiceID) FROM ' + QUOTENAME(@TargetDB) + N'.dbo.Invoices)
) AS checks
ORDER BY TableName;';

EXEC sys.sp_executesql @Sql, N'@SourceDB SYSNAME, @TargetDB SYSNAME', @SourceDB = @SourceDB, @TargetDB = @TargetDB;

SET @Sql = N'
SELECT TOP (100)
    IssueType = ''DUPLICATE_BARCODE_BETWEEN_SOURCE_TARGET'',
    src.ProductID AS SourceProductID,
    tgt.ProductID AS TargetProductID,
    src.BarcodeNumber,
    src.ProductName AS SourceProductName,
    tgt.ProductName AS TargetProductName
FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products AS src
JOIN ' + QUOTENAME(@TargetDB) + N'.dbo.Products AS tgt
  ON NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') = NULLIF(LTRIM(RTRIM(tgt.BarcodeNumber)), '''')
WHERE NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') IS NOT NULL
ORDER BY src.BarcodeNumber;';

EXEC sys.sp_executesql @Sql;
