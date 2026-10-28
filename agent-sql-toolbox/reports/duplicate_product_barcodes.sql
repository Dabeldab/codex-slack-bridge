/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Duplicate products.sql".
Purpose: read-only duplicate/suspicious product barcode scan for the current POS database.
*/

SET NOCOUNT ON;

DECLARE @OnlyAvailableProducts BIT = 1;
DECLARE @BarcodeMinLength INT = 12;
DECLARE @SpecificBarcode NVARCHAR(80) = NULL;

;WITH ProductScope AS (
    SELECT
        ProductID,
        ProductName,
        BarcodeNumber,
        BarcodeNumber2,
        SKU,
        ProductIsAvailable
    FROM dbo.Products
    WHERE (@OnlyAvailableProducts = 0 OR ProductIsAvailable = 1)
      AND (@SpecificBarcode IS NULL OR BarcodeNumber = @SpecificBarcode OR BarcodeNumber2 = @SpecificBarcode)
),
DuplicateBarcodes AS (
    SELECT BarcodeNumber
    FROM ProductScope
    WHERE NULLIF(LTRIM(RTRIM(BarcodeNumber)), '') IS NOT NULL
    GROUP BY BarcodeNumber
    HAVING COUNT(*) > 1
)
SELECT
    'DUPLICATE_BARCODE' AS IssueType,
    product.ProductID,
    product.ProductName,
    product.BarcodeNumber,
    product.BarcodeNumber2,
    product.SKU,
    product.ProductIsAvailable
FROM ProductScope AS product
WHERE EXISTS (SELECT 1 FROM DuplicateBarcodes AS dup WHERE dup.BarcodeNumber = product.BarcodeNumber)
ORDER BY product.BarcodeNumber, product.ProductName;

SELECT
    'LONG_BARCODE' AS IssueType,
    ProductID,
    ProductName,
    BarcodeNumber,
    BarcodeNumber2,
    SKU,
    ProductIsAvailable
FROM ProductScope
WHERE LEN(COALESCE(BarcodeNumber, '')) > @BarcodeMinLength
ORDER BY LEN(BarcodeNumber) DESC, BarcodeNumber;
