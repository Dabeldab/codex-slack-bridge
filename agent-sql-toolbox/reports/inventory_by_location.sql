/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Inventory By location.sql" and related inventory reports.
Purpose: read-only inventory/product export by location for the current POS database.
*/

SET NOCOUNT ON;

DECLARE @LocationIdsCsv NVARCHAR(MAX) = NULL; -- example: '1,2,3'
DECLARE @OnlyAvailableProducts BIT = 1;
DECLARE @IncludeZeroQuantity BIT = 1;
DECLARE @CategoryId INT = NULL;

;WITH LocationFilter AS (
    SELECT TRY_CONVERT(INT, value) AS LocationID
    FROM STRING_SPLIT(COALESCE(@LocationIdsCsv, ''), ',')
    WHERE TRY_CONVERT(INT, value) IS NOT NULL
)
SELECT
    loc.LocationID,
    loc.LocationName,
    prod.ProductID,
    prod.ProductIsAvailable,
    parentCategory.Products_CategoryName AS ParentCategoryName,
    category.Products_CategoryName AS CategoryName,
    prod.ProductName,
    prod.ProductDescription,
    prod.BarcodeNumber,
    prod.BarcodeNumber2,
    prod.SKU,
    prod.Size,
    prod.Attr,
    prod.ProductCostPrice,
    prod.ProductMinPrice,
    prod.ProductMarkupPrice,
    inv.Quantity,
    inv.DesiredQuantity,
    inv.MinimumQuantity,
    wholesaler.WholesalerName
FROM dbo.Inventory AS inv
JOIN dbo.Products AS prod ON prod.ProductID = inv.ProductID
JOIN dbo.Locations AS loc ON loc.LocationID = inv.LocationID
LEFT JOIN dbo.Products_Categories AS category ON category.Products_CategoryID = prod.Product_CategoryID
LEFT JOIN dbo.Products_Categories AS parentCategory ON parentCategory.Products_CategoryID = category.ParentID
LEFT JOIN dbo.Products_Wholesalers AS wholesaler ON wholesaler.WholesalerID = prod.WholesalerID
WHERE (@OnlyAvailableProducts = 0 OR prod.ProductIsAvailable = 1)
  AND (@IncludeZeroQuantity = 1 OR COALESCE(inv.Quantity, 0) <> 0)
  AND (@CategoryId IS NULL OR prod.Product_CategoryID = @CategoryId OR category.ParentID = @CategoryId)
  AND (
        @LocationIdsCsv IS NULL
        OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = inv.LocationID)
      )
ORDER BY loc.LocationName, parentCategory.Products_CategoryName, category.Products_CategoryName, prod.ProductName
OPTION (RECOMPILE);
