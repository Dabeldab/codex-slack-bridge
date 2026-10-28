/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Inventory Count.sql".
Purpose: read-only submitted inventory count detail for the current POS database.
*/

SET NOCOUNT ON;

DECLARE @InventoryCountIdsCsv NVARCHAR(MAX) = NULL; -- example: '476,477'
DECLARE @StartDate DATETIME2(0) = NULL;
DECLARE @EndDateExclusive DATETIME2(0) = NULL;
DECLARE @LocationIdsCsv NVARCHAR(MAX) = NULL;

IF @InventoryCountIdsCsv IS NULL AND @StartDate IS NULL AND @LocationIdsCsv IS NULL
BEGIN
    THROW 51000, 'Set @InventoryCountIdsCsv, @StartDate/@EndDateExclusive, or @LocationIdsCsv before running.', 1;
END;

;WITH CountFilter AS (
    SELECT TRY_CONVERT(INT, value) AS InventoryCountID
    FROM STRING_SPLIT(COALESCE(@InventoryCountIdsCsv, ''), ',')
    WHERE TRY_CONVERT(INT, value) IS NOT NULL
),
LocationFilter AS (
    SELECT TRY_CONVERT(INT, value) AS LocationID
    FROM STRING_SPLIT(COALESCE(@LocationIdsCsv, ''), ',')
    WHERE TRY_CONVERT(INT, value) IS NOT NULL
)
SELECT
    ic.InventoryCountID,
    loc.LocationID,
    loc.LocationName,
    emp.EmployeeName AS SubmittedBy,
    ic.[Timestamp],
    ic.[Status],
    product.ProductID,
    product.BarcodeNumber,
    product.SKU,
    wholesaler.WholesalerName,
    category.Products_CategoryName AS CategoryName,
    product.ProductName,
    product.ProductDescription,
    product.Size,
    product.Attr,
    product.ProductIsAvailable,
    productInventory.Quantity AS CurrentQuantity,
    icp.[Count] AS CountedQuantity,
    icp.[Count] - COALESCE(productInventory.Quantity, 0) AS QuantityDelta
FROM dbo.Inventory_Counts AS ic
LEFT JOIN dbo.Inventory_Counts_Products AS icp ON icp.InventoryCountID = ic.InventoryCountID
LEFT JOIN dbo.Products AS product ON product.ProductID = icp.ProductID
LEFT JOIN dbo.Inventory AS productInventory
    ON productInventory.ProductID = icp.ProductID
   AND productInventory.LocationID = ic.LocationID
LEFT JOIN dbo.Locations AS loc ON loc.LocationID = ic.LocationID
LEFT JOIN dbo.Employees AS emp ON emp.EmployeeID = ic.EmployeeID
LEFT JOIN dbo.Products_Wholesalers AS wholesaler ON wholesaler.WholesalerID = product.WholesalerID
LEFT JOIN dbo.Products_Categories AS category ON category.Products_CategoryID = product.Product_CategoryID
WHERE (
        @InventoryCountIdsCsv IS NULL
        OR EXISTS (SELECT 1 FROM CountFilter AS cf WHERE cf.InventoryCountID = ic.InventoryCountID)
      )
  AND (@StartDate IS NULL OR ic.[Timestamp] >= @StartDate)
  AND (@EndDateExclusive IS NULL OR ic.[Timestamp] < @EndDateExclusive)
  AND (
        @LocationIdsCsv IS NULL
        OR EXISTS (SELECT 1 FROM LocationFilter AS lf WHERE lf.LocationID = ic.LocationID)
      )
ORDER BY ic.InventoryCountID, product.ProductName
OPTION (RECOMPILE);
