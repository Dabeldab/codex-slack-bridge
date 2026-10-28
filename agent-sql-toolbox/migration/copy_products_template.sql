/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "CopyProducts.sql", "3D-Products&Kits.sql", and product copy variants.
Purpose: copy products using target-generated IDs and natural-key matching.
Default: dry run. If @Execute = 1 without @CommitChanges = 1 and the commit
phrase, the transaction is rolled back.
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @SourceDB SYSNAME = N'POS_SOURCE_ACCOUNT';
DECLARE @SourceLocationID INT = NULL;
DECLARE @TargetLocationID INT = NULL;
DECLARE @OnlyAvailableProducts BIT = 1;
DECLARE @CopyInventory BIT = 1;
DECLARE @Execute BIT = 0;
DECLARE @CommitChanges BIT = 0;
DECLARE @ConfirmCommitPhrase NVARCHAR(80) = N''; -- must equal: COMMIT PRODUCT COPY

IF DB_ID(@SourceDB) IS NULL
BEGIN
    THROW 51000, 'Source database was not found on this SQL Server.', 1;
END;

IF @CopyInventory = 1 AND (@SourceLocationID IS NULL OR @TargetLocationID IS NULL)
BEGIN
    THROW 51000, 'Inventory copy requires @SourceLocationID and @TargetLocationID.', 1;
END;

DECLARE @Sql NVARCHAR(MAX) = N'
SELECT
    ExecutionMode = CASE WHEN @Execute = 1 THEN ''WILL_INSERT'' ELSE ''DRY_RUN_ONLY'' END,
    SourceProducts = COUNT_BIG(*),
    AlreadyMatchedInTarget = SUM(CASE WHEN tgt.ProductID IS NULL THEN 0 ELSE 1 END),
    MissingInTarget = SUM(CASE WHEN tgt.ProductID IS NULL THEN 1 ELSE 0 END)
FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products AS src
LEFT JOIN dbo.Products AS tgt
  ON (
        NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') IS NOT NULL
        AND NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') = NULLIF(LTRIM(RTRIM(tgt.BarcodeNumber)), '''')
     )
  OR (
        NULLIF(LTRIM(RTRIM(src.SKU)), '''') IS NOT NULL
        AND NULLIF(LTRIM(RTRIM(src.SKU)), '''') = NULLIF(LTRIM(RTRIM(tgt.SKU)), '''')
     )
WHERE (@OnlyAvailableProducts = 0 OR src.ProductIsAvailable = 1);';

EXEC sys.sp_executesql
    @Sql,
    N'@OnlyAvailableProducts BIT, @Execute BIT',
    @OnlyAvailableProducts = @OnlyAvailableProducts,
    @Execute = @Execute;

SET @Sql = N'
SELECT TOP (100)
    IssueType = ''SOURCE_TARGET_NATURAL_KEY_COLLISION'',
    src.ProductID AS SourceProductID,
    tgt.ProductID AS TargetProductID,
    src.ProductName AS SourceProductName,
    tgt.ProductName AS TargetProductName,
    src.BarcodeNumber,
    src.SKU
FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products AS src
JOIN dbo.Products AS tgt
  ON (
        NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') IS NOT NULL
        AND NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') = NULLIF(LTRIM(RTRIM(tgt.BarcodeNumber)), '''')
     )
  OR (
        NULLIF(LTRIM(RTRIM(src.SKU)), '''') IS NOT NULL
        AND NULLIF(LTRIM(RTRIM(src.SKU)), '''') = NULLIF(LTRIM(RTRIM(tgt.SKU)), '''')
     )
WHERE (@OnlyAvailableProducts = 0 OR src.ProductIsAvailable = 1)
ORDER BY src.ProductName;';

EXEC sys.sp_executesql @Sql, N'@OnlyAvailableProducts BIT', @OnlyAvailableProducts = @OnlyAvailableProducts;

IF @Execute = 1
BEGIN
    IF @CommitChanges = 1 AND @ConfirmCommitPhrase <> N'COMMIT PRODUCT COPY'
    BEGIN
        THROW 51001, 'Commit blocked. Set @ConfirmCommitPhrase = N''COMMIT PRODUCT COPY'' after explicit authorization.', 1;
    END;

    BEGIN TRY
    BEGIN TRAN;

    SET @Sql = N'
    INSERT INTO dbo.Products_Categories (Products_CategoryName, ParentID, Products_CategoryPhoto)
    SELECT DISTINCT srcCat.Products_CategoryName, -1, srcCat.Products_CategoryPhoto
    FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products_Categories AS srcCat
    JOIN ' + QUOTENAME(@SourceDB) + N'.dbo.Products AS srcProd
      ON srcProd.Product_CategoryID = srcCat.Products_CategoryID
    LEFT JOIN dbo.Products_Categories AS tgtCat
      ON tgtCat.Products_CategoryName = srcCat.Products_CategoryName
    WHERE tgtCat.Products_CategoryID IS NULL
      AND (@OnlyAvailableProducts = 0 OR srcProd.ProductIsAvailable = 1);';
    EXEC sys.sp_executesql @Sql, N'@OnlyAvailableProducts BIT', @OnlyAvailableProducts = @OnlyAvailableProducts;

    SET @Sql = N'
    INSERT INTO dbo.Products_Wholesalers (WholesalerName, WholesalerEmail)
    SELECT DISTINCT srcWh.WholesalerName, srcWh.WholesalerEmail
    FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products_Wholesalers AS srcWh
    JOIN ' + QUOTENAME(@SourceDB) + N'.dbo.Products AS srcProd
      ON srcProd.WholesalerID = srcWh.WholesalerID
    LEFT JOIN dbo.Products_Wholesalers AS tgtWh
      ON tgtWh.WholesalerName = srcWh.WholesalerName
    WHERE tgtWh.WholesalerID IS NULL
      AND (@OnlyAvailableProducts = 0 OR srcProd.ProductIsAvailable = 1);';
    EXEC sys.sp_executesql @Sql, N'@OnlyAvailableProducts BIT', @OnlyAvailableProducts = @OnlyAvailableProducts;

    SET @Sql = N'
    INSERT INTO dbo.Products (
        ProductName, ProductPhoto, ProductDescription, ProductCostPrice, ProductMinPrice,
        ProductMarkupPrice, ProductIsAvailable, BarcodeNumber, BarcodeNumber2, Color,
        WholesalerID, ProductComission, Product_CategoryID, IsFixedPrice, Size, Attr,
        IsDiffTaxRate, DiffTaxRate, IsLockProductMarkupPrice, IsTaxIncluded, SKU,
        LastPurchaseCostPrice, IsLockProductMinimumPrice, CommissionType, IsTracked,
        VariantName1, VariantName2, CreatedBy
    )
    SELECT
        src.ProductName, src.ProductPhoto, src.ProductDescription, src.ProductCostPrice, src.ProductMinPrice,
        src.ProductMarkupPrice, src.ProductIsAvailable, src.BarcodeNumber, src.BarcodeNumber2, src.Color,
        tgtWh.WholesalerID, src.ProductComission, tgtCat.Products_CategoryID, src.IsFixedPrice, src.Size, src.Attr,
        src.IsDiffTaxRate, src.DiffTaxRate, src.IsLockProductMarkupPrice, src.IsTaxIncluded, src.SKU,
        src.LastPurchaseCostPrice, src.IsLockProductMinimumPrice, src.CommissionType, src.IsTracked,
        src.VariantName1, src.VariantName2, src.CreatedBy
    FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Products AS src
    LEFT JOIN ' + QUOTENAME(@SourceDB) + N'.dbo.Products_Categories AS srcCat
      ON srcCat.Products_CategoryID = src.Product_CategoryID
    LEFT JOIN dbo.Products_Categories AS tgtCat
      ON tgtCat.Products_CategoryName = srcCat.Products_CategoryName
    LEFT JOIN ' + QUOTENAME(@SourceDB) + N'.dbo.Products_Wholesalers AS srcWh
      ON srcWh.WholesalerID = src.WholesalerID
    LEFT JOIN dbo.Products_Wholesalers AS tgtWh
      ON tgtWh.WholesalerName = srcWh.WholesalerName
    LEFT JOIN dbo.Products AS tgt
      ON (
            NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') IS NOT NULL
            AND NULLIF(LTRIM(RTRIM(src.BarcodeNumber)), '''') = NULLIF(LTRIM(RTRIM(tgt.BarcodeNumber)), '''')
         )
      OR (
            NULLIF(LTRIM(RTRIM(src.SKU)), '''') IS NOT NULL
            AND NULLIF(LTRIM(RTRIM(src.SKU)), '''') = NULLIF(LTRIM(RTRIM(tgt.SKU)), '''')
         )
    WHERE tgt.ProductID IS NULL
      AND (@OnlyAvailableProducts = 0 OR src.ProductIsAvailable = 1);';
    EXEC sys.sp_executesql @Sql, N'@OnlyAvailableProducts BIT', @OnlyAvailableProducts = @OnlyAvailableProducts;

    IF @CopyInventory = 1
    BEGIN
        SET @Sql = N'
        MERGE dbo.Inventory AS tgt
        USING (
            SELECT
                @TargetLocationID AS LocationID,
                tgtProd.ProductID,
                srcInv.Quantity,
                srcInv.DesiredQuantity,
                srcInv.MinimumQuantity
            FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Inventory AS srcInv
            JOIN ' + QUOTENAME(@SourceDB) + N'.dbo.Products AS srcProd
              ON srcProd.ProductID = srcInv.ProductID
            JOIN dbo.Products AS tgtProd
              ON (
                    NULLIF(LTRIM(RTRIM(srcProd.BarcodeNumber)), '''') IS NOT NULL
                    AND NULLIF(LTRIM(RTRIM(srcProd.BarcodeNumber)), '''') = NULLIF(LTRIM(RTRIM(tgtProd.BarcodeNumber)), '''')
                 )
              OR (
                    NULLIF(LTRIM(RTRIM(srcProd.SKU)), '''') IS NOT NULL
                    AND NULLIF(LTRIM(RTRIM(srcProd.SKU)), '''') = NULLIF(LTRIM(RTRIM(tgtProd.SKU)), '''')
                 )
            WHERE srcInv.LocationID = @SourceLocationID
        ) AS src
        ON tgt.LocationID = src.LocationID AND tgt.ProductID = src.ProductID
        WHEN MATCHED THEN
            UPDATE SET Quantity = src.Quantity,
                       DesiredQuantity = src.DesiredQuantity,
                       MinimumQuantity = src.MinimumQuantity
        WHEN NOT MATCHED THEN
            INSERT (LocationID, ProductID, Quantity, DesiredQuantity, MinimumQuantity)
            VALUES (src.LocationID, src.ProductID, src.Quantity, src.DesiredQuantity, src.MinimumQuantity);';
        EXEC sys.sp_executesql
            @Sql,
            N'@SourceLocationID INT, @TargetLocationID INT',
            @SourceLocationID = @SourceLocationID,
            @TargetLocationID = @TargetLocationID;
    END;

        IF @CommitChanges = 1
        BEGIN
            COMMIT TRAN;
            SELECT 'COMMITTED' AS TransactionStatus;
        END
        ELSE
        BEGIN
            ROLLBACK TRAN;
            SELECT 'ROLLED_BACK_PREVIEW_ONLY' AS TransactionStatus;
        END;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
        BEGIN
            ROLLBACK TRAN;
        END;
        THROW;
    END CATCH;
END;
