/*
AgentChat/coding_agent 2026-07-28

Fixed demo validation of the Nova account-copy pattern originally prepared in
Alex's nova_clone_toolbox.  The broker supplies these four declarations:

  @Apply, @OperatorIdempotencyKey, @OperatorPlanHash,
  @ExpectedTargetStateHash

This batch:
  * reads POS_LE_BOUTIQUE_INSTYLE and POS_Instyle_Fragrance only;
  * writes only POS_DEMO_NOVA_CAFE, which must be the current database;
  * runs the copy and remapping on SQL Server with INSERT ... SELECT;
  * keeps the ProductID-DESC winner for the normalized
    ProductName + BarcodeNumber + BarcodeNumber2 + SKU key;
  * copies only missing transformed keys, so the same batch is resumable;
  * creates populated inactive products for true orphan product references;
  * copies missing InventoryHistoryItem rows set-wise instead of relaying them
    through Python;
  * repairs the known blank Instyle Fragrance invoice links; and
  * commits only after Nova-specific dedupe, orphan, blank-field, location,
    region, and history-coverage checks pass.

For a future live target, the same reviewed SQL can be parameterized in a new
typed operation after the exact target and offsets are previewed.  This deployed
operation deliberately keeps all three database names fixed.
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @SourceA sysname=N'POS_LE_BOUTIQUE_INSTYLE';
DECLARE @SourceB sysname=N'POS_Instyle_Fragrance';
DECLARE @Target sysname=N'POS_DEMO_NOVA_CAFE';
DECLARE @SourceAOffset bigint=0;
DECLARE @SourceBOffset bigint=1000000000;
DECLARE @StartedAt datetime2(7)=SYSUTCDATETIME();
DECLARE @RunId uniqueidentifier=NEWID();
DECLARE @Sql nvarchar(max);
DECLARE @Rows bigint;
DECLARE @ProductsInserted bigint=0;
DECLARE @PlaceholdersInserted bigint=0;
DECLARE @ProductReferencesRepaired bigint=0;
DECLARE @FixedInvoiceLinksRepaired bigint=0;
DECLARE @ExpectedHistoryRows bigint=0;

IF @Apply<>1
    THROW 53100,'The fixed broker must explicitly select execute mode.',1;
IF NULLIF(LTRIM(RTRIM(@OperatorIdempotencyKey)),N'') IS NULL
    THROW 53101,'A stable idempotency key is required.',1;
IF LEN(@OperatorPlanHash)<>64 OR @OperatorPlanHash LIKE '%[^0-9a-f]%'
    THROW 53102,'The exact preview hash is required.',1;
IF LEN(@ExpectedTargetStateHash)<>64 OR @ExpectedTargetStateHash LIKE '%[^0-9a-f]%'
    THROW 53103,'The exact preview target-state hash is required.',1;
IF DB_NAME()<>@Target
    THROW 53104,'The developer connection is not bound to POS_DEMO_NOVA_CAFE.',1;
IF DB_ID(@SourceA) IS NULL OR DB_ID(@SourceB) IS NULL OR DB_ID(@Target) IS NULL
    THROW 53105,'One or more fixed Instyle databases is unavailable.',1;
IF HAS_DBACCESS(@SourceA)<>1 OR HAS_DBACCESS(@SourceB)<>1
    THROW 53106,'The fixed broker cannot read both Instyle sources.',1;

CREATE TABLE #CopyResults(
    SourceTag char(1) NOT NULL,
    TableName sysname NOT NULL,
    RowsInserted bigint NOT NULL
);
CREATE TABLE #SkippedTables(
    SourceTag char(1) NOT NULL,
    TableName sysname NOT NULL,
    Reason nvarchar(250) NOT NULL
);

/* Product key inventory: only five small fields are materialized. */
CREATE TABLE #SourceProducts(
    SourceTag char(1) NOT NULL,
    SourceProductID int NOT NULL,
    KeyHash binary(32) NOT NULL,
    IsBlankKey bit NOT NULL,
    PRIMARY KEY(SourceTag,SourceProductID)
);

SET @Sql=N'
INSERT #SourceProducts(SourceTag,SourceProductID,KeyHash,IsBlankKey)
SELECT @Tag,p.ProductID,
 HASHBYTES(''SHA2_256'',CONVERT(nvarchar(max),
   CASE WHEN n.NormName=N'''' AND n.NormBarcode1=N'''' AND
             n.NormBarcode2=N'''' AND n.NormSku=N''''
        THEN CONCAT(N''__source__:'',@Tag,N'':'',p.ProductID)
        ELSE CONCAT(n.NormName,NCHAR(31),n.NormBarcode1,NCHAR(31),
                    n.NormBarcode2,NCHAR(31),n.NormSku) END)),
 CONVERT(bit,CASE WHEN n.NormName=N'''' AND n.NormBarcode1=N'''' AND
                       n.NormBarcode2=N'''' AND n.NormSku=N''''
                  THEN 1 ELSE 0 END)
FROM '+QUOTENAME(@SourceA)+N'.dbo.Products p
CROSS APPLY(SELECT
 LOWER(LTRIM(RTRIM(ISNULL(p.ProductName,N'''')))) NormName,
 LOWER(REPLACE(LTRIM(RTRIM(ISNULL(p.BarcodeNumber,N''''))),N'' '',N'''')) NormBarcode1,
 LOWER(REPLACE(LTRIM(RTRIM(ISNULL(p.BarcodeNumber2,N''''))),N'' '',N'''')) NormBarcode2,
 LOWER(REPLACE(LTRIM(RTRIM(ISNULL(p.SKU,N''''))),N'' '',N'''')) NormSku) n;';
EXEC sys.sp_executesql @Sql,N'@Tag char(1)',@Tag='A';
SET @Sql=REPLACE(@Sql,QUOTENAME(@SourceA),QUOTENAME(@SourceB));
EXEC sys.sp_executesql @Sql,N'@Tag char(1)',@Tag='B';

;WITH Ranked AS(
    SELECT SourceTag,SourceProductID,KeyHash,IsBlankKey,
           rn=ROW_NUMBER() OVER(
               PARTITION BY KeyHash
               ORDER BY SourceProductID DESC,SourceTag DESC)
    FROM #SourceProducts
)
SELECT SourceTag,SourceProductID,KeyHash,IsBlankKey
INTO #ProductWinners
FROM Ranked
WHERE rn=1;
CREATE UNIQUE CLUSTERED INDEX CX_ProductWinners
    ON #ProductWinners(KeyHash);

CREATE TABLE #TargetProductKeys(
    ProductID int NOT NULL,
    KeyHash binary(32) NOT NULL,
    IsBlankKey bit NOT NULL
);
INSERT #TargetProductKeys(ProductID,KeyHash,IsBlankKey)
SELECT p.ProductID,
 HASHBYTES('SHA2_256',CONVERT(nvarchar(max),
   CASE WHEN n.NormName=N'' AND n.NormBarcode1=N'' AND
             n.NormBarcode2=N'' AND n.NormSku=N''
        THEN CONCAT(N'__target__:',p.ProductID)
        ELSE CONCAT(n.NormName,NCHAR(31),n.NormBarcode1,NCHAR(31),
                    n.NormBarcode2,NCHAR(31),n.NormSku) END)),
 CONVERT(bit,CASE WHEN n.NormName=N'' AND n.NormBarcode1=N'' AND
                       n.NormBarcode2=N'' AND n.NormSku=N''
                  THEN 1 ELSE 0 END)
FROM dbo.Products p
CROSS APPLY(SELECT
 LOWER(LTRIM(RTRIM(ISNULL(p.ProductName,N'')))) NormName,
 LOWER(REPLACE(LTRIM(RTRIM(ISNULL(p.BarcodeNumber,N''))),N' ',N'')) NormBarcode1,
 LOWER(REPLACE(LTRIM(RTRIM(ISNULL(p.BarcodeNumber2,N''))),N' ',N'')) NormBarcode2,
 LOWER(REPLACE(LTRIM(RTRIM(ISNULL(p.SKU,N''))),N' ',N'')) NormSku) n;
CREATE INDEX IX_TargetProductKeys_KeyHash ON #TargetProductKeys(KeyHash);

IF EXISTS(
    SELECT 1 FROM #TargetProductKeys
    WHERE IsBlankKey=0
    GROUP BY KeyHash
    HAVING COUNT_BIG(*)>1
)
    THROW 53107,'The demo target already contains duplicate nonblank product keys.',1;

CREATE TABLE #WinnerTargets(
    WinnerSourceTag char(1) NOT NULL,
    WinnerSourceProductID int NOT NULL,
    KeyHash binary(32) NOT NULL,
    TargetProductID int NOT NULL,
    IsNew bit NOT NULL,
    PRIMARY KEY(KeyHash)
);

INSERT #WinnerTargets(
    WinnerSourceTag,WinnerSourceProductID,KeyHash,TargetProductID,IsNew
)
SELECT w.SourceTag,w.SourceProductID,w.KeyHash,t.ProductID,0
FROM #ProductWinners w
JOIN #TargetProductKeys t ON t.KeyHash=w.KeyHash
WHERE w.IsBlankKey=0;

DECLARE @NextProductID bigint=ISNULL((SELECT MAX(CONVERT(bigint,ProductID))
                                      FROM dbo.Products),0);
/* Keep new broker-assigned IDs above both historic source-ID ranges. */
IF @NextProductID<1500000000 SET @NextProductID=1500000000;
;WITH Missing AS(
    SELECT w.*,
           rn=ROW_NUMBER() OVER(
               ORDER BY w.SourceProductID,w.SourceTag,w.KeyHash)
    FROM #ProductWinners w
    WHERE NOT EXISTS(
        SELECT 1 FROM #WinnerTargets x WHERE x.KeyHash=w.KeyHash
    )
)
INSERT #WinnerTargets(
    WinnerSourceTag,WinnerSourceProductID,KeyHash,TargetProductID,IsNew
)
SELECT SourceTag,SourceProductID,KeyHash,
       CONVERT(int,@NextProductID+rn),1
FROM Missing;
IF EXISTS(SELECT 1 FROM #WinnerTargets WHERE TargetProductID<=0)
   OR @NextProductID+(SELECT COUNT_BIG(*) FROM #WinnerTargets WHERE IsNew=1)
      >2147483647
    THROW 53108,'The target ProductID range cannot hold the canonical products.',1;

CREATE TABLE #ProductMap(
    SourceTag char(1) NOT NULL,
    SourceProductID int NOT NULL,
    TargetProductID int NOT NULL,
    KeyHash binary(32) NOT NULL,
    IsPlaceholder bit NOT NULL,
    PRIMARY KEY(SourceTag,SourceProductID)
);
CREATE INDEX IX_ProductMap_Target ON #ProductMap(TargetProductID);

INSERT #ProductMap(
    SourceTag,SourceProductID,TargetProductID,KeyHash,IsPlaceholder
)
SELECT s.SourceTag,s.SourceProductID,w.TargetProductID,s.KeyHash,0
FROM #SourceProducts s
JOIN #WinnerTargets w ON w.KeyHash=s.KeyHash;

/*
Build the same ID transformation rules Alex's runner used, once, from target
keys/FKs plus Nova's known relationship names. External-provider IDs are
deliberately excluded.
*/
CREATE TABLE #ColumnRules(
    TableName sysname NOT NULL,
    ColumnName sysname NOT NULL,
    NormalizedName varchar(128) NOT NULL,
    IsNumeric bit NOT NULL,
    IsProductReference bit NOT NULL,
    ShouldOffset bit NOT NULL,
    PRIMARY KEY(TableName,ColumnName)
);

;WITH Base AS(
    SELECT t.object_id,t.name TableName,c.column_id,c.name ColumnName,
           NormalizedName=LOWER(REPLACE(REPLACE(REPLACE(
               c.name,'_',''),'-',''),' ','')),
           IsNumeric=CONVERT(bit,CASE WHEN ty.name IN(
               'tinyint','smallint','int','bigint','decimal','numeric')
               THEN 1 ELSE 0 END),
           c.is_identity
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id=t.schema_id AND s.name='dbo'
    JOIN sys.columns c ON c.object_id=t.object_id
    JOIN sys.types ty ON ty.user_type_id=c.user_type_id
    WHERE t.is_ms_shipped=0
), Relationships AS(
    SELECT b.*,
           IsKey=CONVERT(bit,CASE WHEN b.is_identity=1
              OR EXISTS(SELECT 1 FROM sys.indexes i
                        JOIN sys.index_columns ic
                          ON ic.object_id=i.object_id
                         AND ic.index_id=i.index_id
                        WHERE i.object_id=b.object_id
                          AND i.is_primary_key=1
                          AND ic.column_id=b.column_id)
              OR EXISTS(SELECT 1 FROM sys.foreign_key_columns fk
                        WHERE fk.parent_object_id=b.object_id
                          AND fk.parent_column_id=b.column_id)
              THEN 1 ELSE 0 END)
    FROM Base b
)
INSERT #ColumnRules(
    TableName,ColumnName,NormalizedName,IsNumeric,
    IsProductReference,ShouldOffset
)
SELECT TableName,ColumnName,NormalizedName,IsNumeric,
       CONVERT(bit,CASE WHEN NormalizedName IN(
           'productid','originalproductid') THEN 1 ELSE 0 END),
       CONVERT(bit,CASE
        WHEN IsNumeric=0 THEN 0
        WHEN NormalizedName IN(
          'salesbuildercustomerid','salesbuilderinvoiceid',
          'salesforcecontactid','emvdeviceid','deviceid',
          'paymentgatewayid','timezoneid','competitionid',
          'competitionmethodid','weborderlineitemid',
          'originaltransactionid','transactionidentifier',
          'productidentifier','taxid','offlineinvoiceid') THEN 0
        WHEN IsKey=1 THEN 1
        WHEN NormalizedName IN(
          'alertid','mastereventid','parentid','objectrefid','typereferid',
          'profileimagefileid','refundinvoiceid','originalpaymentid',
          'fromvendorid','kitid','invoiceproductsid','ipadsubscriptionid',
          'pendinginvoiceid','productfamilyid','pricelistid','createdby')
          THEN 1
        WHEN NormalizedName LIKE '%productid'
          OR NormalizedName LIKE '%locationid'
          OR NormalizedName LIKE '%employeeid'
          OR NormalizedName LIKE '%customerid'
          OR NormalizedName LIKE '%invoiceid'
          OR NormalizedName LIKE '%refundid'
          OR NormalizedName LIKE '%regionid'
          OR NormalizedName LIKE '%couponid'
          OR NormalizedName LIKE '%roleid'
          OR NormalizedName LIKE '%wholesalerid'
          OR NormalizedName LIKE '%storageorderid'
          OR NormalizedName LIKE '%customerorderid'
          OR NormalizedName LIKE '%inventorycountid'
          OR NormalizedName LIKE '%inventoryhistoryid'
          OR NormalizedName LIKE '%inventoryhistorysettingsid'
          OR NormalizedName LIKE '%propertyvalueid'
          THEN 1
        ELSE 0 END)
FROM Relationships;

/*
This legacy junction has no declared FK in the demo schema, but its parent
Alerts_History rows are source-B offset.  Keep the child reference aligned.
*/
UPDATE #ColumnRules
SET ShouldOffset=1
WHERE TableName='Alerts_History_Employees'
  AND ColumnName='AlertsHistoryId';

/*
Find genuine product references in each source whose Products parent no longer
exists.  These are mapped to populated inactive placeholders, never left blank.
*/
CREATE TABLE #SourceProductOrphans(
    SourceTag char(1) NOT NULL,
    SourceProductID int NOT NULL,
    PRIMARY KEY(SourceTag,SourceProductID)
);
CREATE TABLE #ProductReferencePlan(
    TableName sysname NOT NULL,
    ColumnName sysname NOT NULL,
    PRIMARY KEY(TableName,ColumnName)
);
INSERT #ProductReferencePlan VALUES
('Coupons_Products','ProductID'),
('CustomerOrders_Products','ProductID'),
('Inventory','ProductID'),
('Inventory_Counts_Products','ProductID'),
('Inventory_Damage','ProductID'),
('Inventory_Transactions','ProductID'),
('InventoryHistoryItem','OriginalProductID'),
('Invoice_Products','ProductID'),
('Invoice_Refunds','ProductID'),
('Pending_Invoice_Product','ProductID'),
('PriceLists_Items','ProductID'),
('ProductFavorites','ProductID'),
('Quote_Products','ProductID'),
('Refunds_Products','ProductID'),
('StorageOrders_Products','ProductID');

DECLARE @PlanTable sysname,@PlanColumn sysname,@SourceTag char(1),@SourceDB sysname;
DECLARE ProductSourceCursor CURSOR LOCAL FAST_FORWARD FOR
SELECT p.TableName,p.ColumnName,s.SourceTag,s.SourceDB
FROM #ProductReferencePlan p
CROSS JOIN(VALUES('A',@SourceA),('B',@SourceB)) s(SourceTag,SourceDB);
OPEN ProductSourceCursor;
FETCH NEXT FROM ProductSourceCursor
INTO @PlanTable,@PlanColumn,@SourceTag,@SourceDB;
WHILE @@FETCH_STATUS=0
BEGIN
    IF EXISTS(
        SELECT 1
        FROM sys.databases
        WHERE name=@SourceDB
    )
    BEGIN
        SET @Sql=N'
IF OBJECT_ID('+QUOTENAME(@SourceDB+N'.dbo.'+@PlanTable,'''')+N',''U'') IS NOT NULL
   AND COL_LENGTH('+QUOTENAME(@SourceDB+N'.dbo.'+@PlanTable,'''')+N',
                  '+QUOTENAME(@PlanColumn,'''')+N') IS NOT NULL
INSERT #SourceProductOrphans(SourceTag,SourceProductID)
SELECT @Tag,x.'+QUOTENAME(@PlanColumn)+N'
FROM '+QUOTENAME(@SourceDB)+N'.dbo.'+QUOTENAME(@PlanTable)+N' x
LEFT JOIN '+QUOTENAME(@SourceDB)+N'.dbo.Products p
  ON p.ProductID=x.'+QUOTENAME(@PlanColumn)+N'
WHERE x.'+QUOTENAME(@PlanColumn)+N'>0
  AND p.ProductID IS NULL
  AND NOT EXISTS(
      SELECT 1 FROM #SourceProductOrphans o
      WHERE o.SourceTag=@Tag
        AND o.SourceProductID=x.'+QUOTENAME(@PlanColumn)+N'
  )
GROUP BY x.'+QUOTENAME(@PlanColumn)+N';';
        EXEC sys.sp_executesql @Sql,N'@Tag char(1)',@Tag=@SourceTag;
    END;
    FETCH NEXT FROM ProductSourceCursor
    INTO @PlanTable,@PlanColumn,@SourceTag,@SourceDB;
END;
CLOSE ProductSourceCursor;
DEALLOCATE ProductSourceCursor;

DECLARE @OrphanBase bigint=ISNULL((
    SELECT MAX(CONVERT(bigint,TargetProductID)) FROM #ProductMap
),@NextProductID);
SET @OrphanBase=CASE
    WHEN @OrphanBase>@NextProductID THEN @OrphanBase ELSE @NextProductID END;

;WITH Missing AS(
    SELECT o.SourceTag,o.SourceProductID,
           rn=ROW_NUMBER() OVER(
               ORDER BY o.SourceProductID,o.SourceTag)
    FROM #SourceProductOrphans o
    WHERE NOT EXISTS(
        SELECT 1 FROM #ProductMap m
        WHERE m.SourceTag=o.SourceTag
          AND m.SourceProductID=o.SourceProductID
    )
)
INSERT #ProductMap(
    SourceTag,SourceProductID,TargetProductID,KeyHash,IsPlaceholder
)
SELECT SourceTag,SourceProductID,CONVERT(int,@OrphanBase+rn),
       HASHBYTES('SHA2_256',CONVERT(nvarchar(max),
          CONCAT(N'__missing__:',SourceTag,N':',SourceProductID))),1
FROM Missing;
IF @OrphanBase+(SELECT COUNT_BIG(*) FROM #SourceProductOrphans)>2147483647
    THROW 53109,'The target ProductID range cannot hold orphan placeholders.',1;

/* Existing target orphan IDs are either remapped or receive a local placeholder. */
CREATE TABLE #TargetOrphanProductIds(
    EncodedProductID int NOT NULL PRIMARY KEY
);
DECLARE TargetOrphanCursor CURSOR LOCAL FAST_FORWARD FOR
SELECT TableName,ColumnName FROM #ProductReferencePlan;
OPEN TargetOrphanCursor;
FETCH NEXT FROM TargetOrphanCursor INTO @PlanTable,@PlanColumn;
WHILE @@FETCH_STATUS=0
BEGIN
    IF OBJECT_ID(N'dbo.'+@PlanTable,'U') IS NOT NULL
       AND COL_LENGTH(N'dbo.'+@PlanTable,@PlanColumn) IS NOT NULL
    BEGIN
        SET @Sql=N'
INSERT #TargetOrphanProductIds(EncodedProductID)
SELECT x.'+QUOTENAME(@PlanColumn)+N'
FROM dbo.'+QUOTENAME(@PlanTable)+N' x
LEFT JOIN dbo.Products p
  ON p.ProductID=x.'+QUOTENAME(@PlanColumn)+N'
WHERE x.'+QUOTENAME(@PlanColumn)+N'>0
  AND p.ProductID IS NULL
  AND NOT EXISTS(
      SELECT 1 FROM #TargetOrphanProductIds o
      WHERE o.EncodedProductID=x.'+QUOTENAME(@PlanColumn)+N'
  )
GROUP BY x.'+QUOTENAME(@PlanColumn)+N';';
        EXEC(@Sql);
    END;
    FETCH NEXT FROM TargetOrphanCursor INTO @PlanTable,@PlanColumn;
END;
CLOSE TargetOrphanCursor;
DEALLOCATE TargetOrphanCursor;

INSERT #ProductMap(
    SourceTag,SourceProductID,TargetProductID,KeyHash,IsPlaceholder
)
SELECT CASE WHEN o.EncodedProductID>=@SourceBOffset THEN 'B' ELSE 'A' END,
       CONVERT(int,CASE WHEN o.EncodedProductID>=@SourceBOffset
                        THEN o.EncodedProductID-@SourceBOffset
                        ELSE o.EncodedProductID END),
       o.EncodedProductID,
       HASHBYTES('SHA2_256',CONVERT(nvarchar(max),
          CONCAT(N'__target_missing__:',o.EncodedProductID))),1
FROM #TargetOrphanProductIds o
WHERE NOT EXISTS(
    SELECT 1 FROM #ProductMap m
    WHERE (m.SourceTag='A'
           AND m.SourceProductID=o.EncodedProductID)
       OR (m.SourceTag='B'
           AND m.SourceProductID=o.EncodedProductID-@SourceBOffset)
);

SET @Sql=N'SELECT @RowsOut=
  (SELECT COUNT_BIG(*) FROM '+QUOTENAME(@SourceA)+N'.dbo.InventoryHistoryItem)+
  (SELECT COUNT_BIG(*) FROM '+QUOTENAME(@SourceB)+N'.dbo.InventoryHistoryItem);';
EXEC sys.sp_executesql
     @Sql,N'@RowsOut bigint OUTPUT',@RowsOut=@ExpectedHistoryRows OUTPUT;

BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @LockResult int;
    EXEC @LockResult=sys.sp_getapplock
         @Resource=N'nova:instyle-demo:set-based-copy',
         @LockMode=N'Exclusive',
         @LockOwner=N'Transaction',
         @LockTimeout=0;
    IF @LockResult<0
        THROW 53110,'Another fixed Instyle demo copy is active.',1;

    IF OBJECT_ID(N'dbo.__codex_instyle_core_product_map','U') IS NULL
    BEGIN
        CREATE TABLE dbo.__codex_instyle_core_product_map(
            SourceTag char(1) NOT NULL,
            SourceProductID int NOT NULL,
            TargetProductID int NOT NULL,
            KeyHash char(64) NOT NULL,
            IsPlaceholder bit NOT NULL,
            UpdatedAtUtc datetime2(7) NOT NULL,
            CONSTRAINT PK___codex_instyle_core_product_map
                PRIMARY KEY(SourceTag,SourceProductID)
        );
        CREATE INDEX IX___codex_instyle_core_product_map_Target
            ON dbo.__codex_instyle_core_product_map(TargetProductID);
    END;

    IF OBJECT_ID(N'dbo.__codex_instyle_set_based_receipts','U') IS NULL
    BEGIN
        CREATE TABLE dbo.__codex_instyle_set_based_receipts(
            IdempotencyKey nvarchar(200) NOT NULL,
            PlanHash char(64) NOT NULL,
            TargetStateHash char(64) NOT NULL,
            RunID uniqueidentifier NOT NULL,
            StartedAtUtc datetime2(7) NOT NULL,
            CompletedAtUtc datetime2(7) NULL,
            ResultJson nvarchar(max) NULL,
            CONSTRAINT PK___codex_instyle_set_based_receipts
                PRIMARY KEY(IdempotencyKey)
        );
    END;

    IF EXISTS(
        SELECT 1
        FROM dbo.__codex_instyle_set_based_receipts
        WHERE IdempotencyKey=@OperatorIdempotencyKey
          AND CompletedAtUtc IS NOT NULL
    )
    BEGIN
        SELECT ResultJson
        FROM dbo.__codex_instyle_set_based_receipts
        WHERE IdempotencyKey=@OperatorIdempotencyKey;
        ROLLBACK TRANSACTION;
        RETURN;
    END;

    IF EXISTS(
        SELECT 1
        FROM dbo.__codex_instyle_set_based_receipts
        WHERE IdempotencyKey=@OperatorIdempotencyKey
    )
    BEGIN
        UPDATE dbo.__codex_instyle_set_based_receipts
        SET PlanHash=@OperatorPlanHash,
            TargetStateHash=@ExpectedTargetStateHash,
            RunID=@RunId,
            StartedAtUtc=@StartedAt,
            CompletedAtUtc=NULL,
            ResultJson=NULL
        WHERE IdempotencyKey=@OperatorIdempotencyKey;
    END
    ELSE
    BEGIN
        INSERT dbo.__codex_instyle_set_based_receipts(
            IdempotencyKey,PlanHash,TargetStateHash,RunID,
            StartedAtUtc,CompletedAtUtc,ResultJson
        )
        VALUES(
            @OperatorIdempotencyKey,@OperatorPlanHash,
            @ExpectedTargetStateHash,@RunId,@StartedAt,NULL,NULL
        );
    END;

    /* Disable enforcement only inside this target transaction. */
    DECLARE @IntegrityTable sysname;
    DECLARE IntegrityCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT t.name
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id=t.schema_id AND s.name='dbo'
    WHERE t.is_ms_shipped=0
      AND t.name NOT LIKE '__codex[_]%';
    OPEN IntegrityCursor;
    FETCH NEXT FROM IntegrityCursor INTO @IntegrityTable;
    WHILE @@FETCH_STATUS=0
    BEGIN
        SET @Sql=N'ALTER TABLE dbo.'+QUOTENAME(@IntegrityTable)+
                 N' NOCHECK CONSTRAINT ALL;';
        EXEC(@Sql);
        SET @Sql=N'DISABLE TRIGGER ALL ON dbo.'+
                 QUOTENAME(@IntegrityTable)+N';';
        EXEC(@Sql);
        FETCH NEXT FROM IntegrityCursor INTO @IntegrityTable;
    END;
    CLOSE IntegrityCursor;
    DEALLOCATE IntegrityCursor;

    /*
    Insert only canonical winners missing from the target.  All field movement is
    one INSERT ... SELECT per source; no product rows pass through Python.
    */
    DECLARE @ProductColumns nvarchar(max),
            @ProductExpressions nvarchar(max),
            @ProductSource sysname,
            @ProductTag char(1),
            @ProductOffset bigint,
            @ProductIdentity bit;
    SELECT @ProductIdentity=CONVERT(bit,MAX(CONVERT(int,c.is_identity)))
    FROM sys.columns c
    WHERE c.object_id=OBJECT_ID(N'dbo.Products')
      AND c.name='ProductID';

    DECLARE ProductInsertCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT SourceTag,SourceDB,OffsetValue
    FROM(VALUES('A',@SourceA,@SourceAOffset),
               ('B',@SourceB,@SourceBOffset))
         x(SourceTag,SourceDB,OffsetValue);
    OPEN ProductInsertCursor;
    FETCH NEXT FROM ProductInsertCursor
    INTO @ProductTag,@ProductSource,@ProductOffset;
    WHILE @@FETCH_STATUS=0
    BEGIN
        SET @ProductColumns=NULL;
        SET @ProductExpressions=NULL;
        SET @Sql=N'
;WITH CompatibleColumns AS(
 SELECT tc.column_id,tc.name,r.IsProductReference,r.ShouldOffset
 FROM sys.columns tc
 JOIN sys.types tt ON tt.user_type_id=tc.user_type_id
 JOIN '+QUOTENAME(@ProductSource)+N'.sys.tables st
   ON st.name=N''Products''
 JOIN '+QUOTENAME(@ProductSource)+N'.sys.schemas ss
   ON ss.schema_id=st.schema_id AND ss.name=N''dbo''
 JOIN '+QUOTENAME(@ProductSource)+N'.sys.columns sc
   ON sc.object_id=st.object_id AND sc.name=tc.name
 JOIN '+QUOTENAME(@ProductSource)+N'.sys.types sty
   ON sty.user_type_id=sc.user_type_id AND sty.name=tt.name
 JOIN #ColumnRules r
   ON r.TableName=N''Products'' AND r.ColumnName=tc.name
 WHERE tc.object_id=OBJECT_ID(N''dbo.Products'')
   AND tc.is_computed=0
   AND tc.generated_always_type=0
   AND tt.name NOT IN(N''timestamp'',N''rowversion'')
)
SELECT
 @Columns=STUFF((
   SELECT N'',''+QUOTENAME(cc.name)
   FROM CompatibleColumns cc
   ORDER BY cc.column_id
   FOR XML PATH(N''''),TYPE
 ).value(N''.'',N''nvarchar(max)''),1,1,N''''),
 @Expressions=STUFF((
   SELECT N'',''+CONVERT(nvarchar(max),
   CASE
    WHEN cc.name=N''ProductID'' THEN N''w.TargetProductID''
    WHEN cc.IsProductReference=1 THEN CONCAT(
      N''CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN COALESCE(
          (SELECT pm.TargetProductID FROM #ProductMap pm
           WHERE pm.SourceTag=@SourceTag
             AND pm.SourceProductID=s.'',QUOTENAME(cc.name),
      N''),s.'',QUOTENAME(cc.name),N''+'',
      CONVERT(nvarchar(30),@Offset),
      N'') ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN @Offset>0 AND cc.ShouldOffset=1 THEN CONCAT(
      N''CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN CONVERT(bigint,s.'',QUOTENAME(cc.name),
      N'')+'',CONVERT(nvarchar(30),@Offset),
      N'' ELSE s.'',QUOTENAME(cc.name),N'' END'')
    ELSE N''s.''+QUOTENAME(cc.name)
   END)
   FROM CompatibleColumns cc
   ORDER BY cc.column_id
   FOR XML PATH(N''''),TYPE
 ).value(N''.'',N''nvarchar(max)''),1,1,N'''');';
        EXEC sys.sp_executesql
             @Sql,
             N'@Offset bigint,
               @Columns nvarchar(max) OUTPUT,
               @Expressions nvarchar(max) OUTPUT',
             @Offset=@ProductOffset,
             @Columns=@ProductColumns OUTPUT,
             @Expressions=@ProductExpressions OUTPUT;

        IF NULLIF(@ProductColumns,N'') IS NULL
           OR NULLIF(@ProductExpressions,N'') IS NULL
            THROW 53111,'A source Products schema is not compatible with the target.',1;

        SET @Sql=N'';
        IF @ProductIdentity=1
            SET @Sql+=N'SET IDENTITY_INSERT dbo.Products ON;';
        SET @Sql+=N'
INSERT dbo.Products('+@ProductColumns+N')
SELECT '+@ProductExpressions+N'
FROM '+QUOTENAME(@ProductSource)+N'.dbo.Products s
JOIN #WinnerTargets w
  ON w.WinnerSourceTag='+QUOTENAME(@ProductTag,'''')+N'
 AND w.WinnerSourceProductID=s.ProductID
WHERE w.IsNew=1
  AND NOT EXISTS(
      SELECT 1 FROM dbo.Products t
      WHERE t.ProductID=w.TargetProductID
  );
SELECT @RowsOut=@@ROWCOUNT;';
        IF @ProductIdentity=1
            SET @Sql+=N'SET IDENTITY_INSERT dbo.Products OFF;';
        SET @Rows=0;
        EXEC sys.sp_executesql
             @Sql,
             N'@SourceTag char(1),@RowsOut bigint OUTPUT',
             @SourceTag=@ProductTag,@RowsOut=@Rows OUTPUT;
        SET @ProductsInserted+=@Rows;

        FETCH NEXT FROM ProductInsertCursor
        INTO @ProductTag,@ProductSource,@ProductOffset;
    END;
    CLOSE ProductInsertCursor;
    DEALLOCATE ProductInsertCursor;

    UPDATE p
    SET ProductName=CONCAT(
        N'Unnamed product [',w.WinnerSourceTag,N':',
        w.WinnerSourceProductID,N']'
    )
    FROM dbo.Products p
    JOIN #WinnerTargets w ON w.TargetProductID=p.ProductID
    WHERE NULLIF(LTRIM(RTRIM(p.ProductName)),N'') IS NULL;

    /*
    Populate placeholder products by cloning the target's own valid defaults and
    replacing every operator-visible key field.  This avoids blank rows and does
    not invent unknown required/default values.
    */
    IF EXISTS(
        SELECT 1 FROM #ProductMap m
        WHERE m.IsPlaceholder=1
          AND NOT EXISTS(
              SELECT 1 FROM dbo.Products p
              WHERE p.ProductID=m.TargetProductID
          )
    )
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM dbo.Products)
            THROW 53112,'No valid target product exists to seed inactive placeholders.',1;

        DECLARE @PlaceholderColumns nvarchar(max),
                @PlaceholderExpressions nvarchar(max);
        ;WITH WritableColumns AS(
            SELECT c.column_id,c.name
            FROM sys.columns c
            JOIN sys.types ty ON ty.user_type_id=c.user_type_id
            WHERE c.object_id=OBJECT_ID(N'dbo.Products')
              AND c.is_computed=0
              AND c.generated_always_type=0
              AND ty.name NOT IN(N'timestamp',N'rowversion')
        )
        SELECT
         @PlaceholderColumns=STUFF((
             SELECT N','+QUOTENAME(c.name)
             FROM WritableColumns c
             ORDER BY c.column_id
             FOR XML PATH(N''),TYPE
         ).value(N'.',N'nvarchar(max)'),1,1,N''),
         @PlaceholderExpressions=STUFF((
             SELECT N','+CONVERT(nvarchar(max),
             CASE
              WHEN c.name='ProductID' THEN N'm.TargetProductID'
              WHEN c.name='ProductName' THEN
                N'CONCAT(N''Inactive missing product ['',m.SourceTag,N'':'',
                         m.SourceProductID,N'']'')'
              WHEN c.name='SKU' THEN
                N'CONCAT(N''MISSING-'',m.SourceTag,N''-'',m.SourceProductID)'
              WHEN c.name='BarcodeNumber' THEN
                N'CONCAT(N''MISSING-'',m.SourceTag,N''-'',m.SourceProductID)'
              WHEN c.name='BarcodeNumber2' THEN
                N'CONCAT(N''MISSING-'',m.SourceTag,N''-'',
                         m.SourceProductID,N''-2'')'
              WHEN LOWER(c.name) IN(
                  'productisavailable','productactive') THEN N'CONVERT(bit,0)'
              ELSE N't.'+QUOTENAME(c.name)
             END)
             FROM WritableColumns c
             ORDER BY c.column_id
             FOR XML PATH(N''),TYPE
         ).value(N'.',N'nvarchar(max)'),1,1,N'');

        SET @Sql=N'';
        IF @ProductIdentity=1
            SET @Sql+=N'SET IDENTITY_INSERT dbo.Products ON;';
        SET @Sql+=N'
INSERT dbo.Products('+@PlaceholderColumns+N')
SELECT '+@PlaceholderExpressions+N'
FROM #ProductMap m
CROSS JOIN(SELECT TOP(1) * FROM dbo.Products ORDER BY ProductID)t
WHERE m.IsPlaceholder=1
  AND NOT EXISTS(
      SELECT 1 FROM dbo.Products p
      WHERE p.ProductID=m.TargetProductID
  );
SELECT @RowsOut=@@ROWCOUNT;';
        IF @ProductIdentity=1
            SET @Sql+=N'SET IDENTITY_INSERT dbo.Products OFF;';
        SET @Rows=0;
        EXEC sys.sp_executesql
             @Sql,N'@RowsOut bigint OUTPUT',@RowsOut=@Rows OUTPUT;
        SET @PlaceholdersInserted=@Rows;
    END;

    UPDATE persisted
    SET persisted.TargetProductID=m.TargetProductID,
        persisted.KeyHash=LOWER(CONVERT(char(64),m.KeyHash,2)),
        persisted.IsPlaceholder=m.IsPlaceholder,
        persisted.UpdatedAtUtc=SYSUTCDATETIME()
    FROM dbo.__codex_instyle_core_product_map persisted
    JOIN #ProductMap m
      ON m.SourceTag=persisted.SourceTag
     AND m.SourceProductID=persisted.SourceProductID;

    INSERT dbo.__codex_instyle_core_product_map(
        SourceTag,SourceProductID,TargetProductID,
        KeyHash,IsPlaceholder,UpdatedAtUtc
    )
    SELECT m.SourceTag,m.SourceProductID,m.TargetProductID,
           LOWER(CONVERT(char(64),m.KeyHash,2)),
           m.IsPlaceholder,SYSUTCDATETIME()
    FROM #ProductMap m
    WHERE NOT EXISTS(
        SELECT 1 FROM dbo.__codex_instyle_core_product_map persisted
        WHERE persisted.SourceTag=m.SourceTag
          AND persisted.SourceProductID=m.SourceProductID
    );

    /*
    Copy every other compatible business table.  One INSERT ... SELECT runs per
    source/table and checks the transformed target key, so reruns insert only
    missing rows.  Log4Net and the broker's own helper tables are intentionally
    excluded; InventoryHistoryItem is included.
    */
    CREATE TABLE #CopyTables(
        SourceTag char(1) NOT NULL,
        SourceDB sysname NOT NULL,
        OffsetValue bigint NOT NULL,
        TableName sysname NOT NULL,
        PRIMARY KEY(SourceTag,TableName)
    );
    DECLARE @CopyInventoryTag char(1),
            @CopyInventoryDB sysname,
            @CopyInventoryOffset bigint;
    DECLARE CopyInventoryCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT SourceTag,SourceDB,OffsetValue
    FROM(VALUES('A',@SourceA,@SourceAOffset),
               ('B',@SourceB,@SourceBOffset))
         s(SourceTag,SourceDB,OffsetValue);
    OPEN CopyInventoryCursor;
    FETCH NEXT FROM CopyInventoryCursor
    INTO @CopyInventoryTag,@CopyInventoryDB,@CopyInventoryOffset;
    WHILE @@FETCH_STATUS=0
    BEGIN
        SET @Sql=N'
INSERT #CopyTables(SourceTag,SourceDB,OffsetValue,TableName)
SELECT @Tag,@Database,@Offset,st.name
FROM '+QUOTENAME(@CopyInventoryDB)+N'.sys.tables st
JOIN '+QUOTENAME(@CopyInventoryDB)+N'.sys.schemas ss
  ON ss.schema_id=st.schema_id AND ss.name=N''dbo''
WHERE st.is_ms_shipped=0
  AND st.name NOT IN(
      N''Products'',N''Log4Net'',
      N''__AgentChat_InstyleMergeCheckpoint'',
      N''__codex_instyle_core_product_map'',
      N''__codex_instyle_set_based_receipts'')
  AND st.name NOT LIKE N''__codex[_]%''
  AND st.name NOT LIKE N''__nova[_]%''
  AND EXISTS(
      SELECT 1 FROM sys.tables tt
      JOIN sys.schemas ts
        ON ts.schema_id=tt.schema_id AND ts.name=N''dbo''
      WHERE tt.name=st.name
  )
  AND EXISTS(
      SELECT 1
      FROM '+QUOTENAME(@CopyInventoryDB)+N'.sys.partitions p
      WHERE p.object_id=st.object_id
        AND p.index_id IN(0,1)
        AND p.rows>0
  );';
        EXEC sys.sp_executesql
             @Sql,
             N'@Tag char(1),@Database sysname,@Offset bigint',
             @Tag=@CopyInventoryTag,@Database=@CopyInventoryDB,
             @Offset=@CopyInventoryOffset;
        FETCH NEXT FROM CopyInventoryCursor
        INTO @CopyInventoryTag,@CopyInventoryDB,@CopyInventoryOffset;
    END;
    CLOSE CopyInventoryCursor;
    DEALLOCATE CopyInventoryCursor;

    DECLARE @CopyTag char(1),@CopySource sysname,@CopyOffset bigint,
            @CopyTable sysname,@CopyColumns nvarchar(max),
            @CopyExpressions nvarchar(max),@KeyPredicate nvarchar(max),
            @KeyColumns nvarchar(max),@NullKeyPredicate nvarchar(max),
            @MultiplicityColumns nvarchar(max),
            @MultiplicityPredicate nvarchar(max),
            @HasIdentity bit,@UsingKeyOverride bit,@AllowDuplicateKey bit,
            @CurrentColumn sysname,@CurrentExpression nvarchar(max),
            @KeyOrdinal int;

    DECLARE CopyCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT SourceTag,SourceDB,OffsetValue,TableName
    FROM #CopyTables
    ORDER BY CASE WHEN TableName='InventoryHistoryItem' THEN 2 ELSE 1 END,
             TableName,SourceTag;
    OPEN CopyCursor;
    FETCH NEXT FROM CopyCursor
    INTO @CopyTag,@CopySource,@CopyOffset,@CopyTable;
    WHILE @@FETCH_STATUS=0
    BEGIN
        SET @CopyColumns=NULL;
        SET @CopyExpressions=NULL;
        SET @KeyPredicate=NULL;
        SET @KeyColumns=NULL;
        SET @NullKeyPredicate=NULL;
        SET @MultiplicityColumns=NULL;
        SET @MultiplicityPredicate=NULL;
        SET @HasIdentity=0;
        SET @UsingKeyOverride=0;
        SET @AllowDuplicateKey=0;

        SET @Sql=N'
;WITH CompatibleColumns AS(
 SELECT tc.column_id,tc.name,tc.is_identity,
        r.IsProductReference,r.ShouldOffset
 FROM sys.tables target_table
 JOIN sys.schemas target_schema
   ON target_schema.schema_id=target_table.schema_id
  AND target_schema.name=N''dbo''
 JOIN sys.columns tc ON tc.object_id=target_table.object_id
 JOIN sys.types tt ON tt.user_type_id=tc.user_type_id
 JOIN '+QUOTENAME(@CopySource)+N'.sys.tables source_table
   ON source_table.name=target_table.name
 JOIN '+QUOTENAME(@CopySource)+N'.sys.schemas source_schema
   ON source_schema.schema_id=source_table.schema_id
  AND source_schema.name=N''dbo''
 JOIN '+QUOTENAME(@CopySource)+N'.sys.columns sc
   ON sc.object_id=source_table.object_id AND sc.name=tc.name
 JOIN '+QUOTENAME(@CopySource)+N'.sys.types sty
   ON sty.user_type_id=sc.user_type_id AND sty.name=tt.name
 JOIN #ColumnRules r
   ON r.TableName=target_table.name AND r.ColumnName=tc.name
 WHERE target_table.name=@TableName
   AND tc.is_computed=0
   AND tc.generated_always_type=0
   AND tt.name NOT IN(N''timestamp'',N''rowversion'')
)
SELECT
 @Columns=STUFF((
   SELECT N'',''+QUOTENAME(cc.name)
   FROM CompatibleColumns cc
   ORDER BY cc.column_id
   FOR XML PATH(N''''),TYPE
 ).value(N''.'',N''nvarchar(max)''),1,1,N''''),
 @Expressions=STUFF((
   SELECT N'',''+CONVERT(nvarchar(max),
   CASE
    WHEN cc.IsProductReference=1 THEN CONCAT(
      N''CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN COALESCE(
          (SELECT pm.TargetProductID FROM #ProductMap pm
           WHERE pm.SourceTag=@SourceTag
             AND pm.SourceProductID=s.'',QUOTENAME(cc.name),
      N''),s.'',QUOTENAME(cc.name),N''+'',
      CONVERT(nvarchar(30),@Offset),
      N'') ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN @Offset>0 AND cc.ShouldOffset=1 THEN CONCAT(
      N''CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN CONVERT(bigint,s.'',QUOTENAME(cc.name),
      N'')+'',CONVERT(nvarchar(30),@Offset),
      N'' ELSE s.'',QUOTENAME(cc.name),N'' END'')
    ELSE N''s.''+QUOTENAME(cc.name)
   END)
   FROM CompatibleColumns cc
   ORDER BY cc.column_id
   FOR XML PATH(N''''),TYPE
 ).value(N''.'',N''nvarchar(max)''),1,1,N''''),
 @HasIdentity=(
   SELECT CONVERT(bit,MAX(CONVERT(int,cc.is_identity)))
   FROM CompatibleColumns cc
 );';
        EXEC sys.sp_executesql
             @Sql,
             N'@Offset bigint,@TableName sysname,
               @Columns nvarchar(max) OUTPUT,
               @Expressions nvarchar(max) OUTPUT,
               @HasIdentity bit OUTPUT',
             @Offset=@CopyOffset,@TableName=@CopyTable,
             @Columns=@CopyColumns OUTPUT,
             @Expressions=@CopyExpressions OUTPUT,
             @HasIdentity=@HasIdentity OUTPUT;

        IF NULLIF(@CopyColumns,N'') IS NULL
           OR NULLIF(@CopyExpressions,N'') IS NULL
        BEGIN
            INSERT #SkippedTables VALUES(
                @CopyTag,@CopyTable,N'no compatible writable columns'
            );
            FETCH NEXT FROM CopyCursor
            INTO @CopyTag,@CopySource,@CopyOffset,@CopyTable;
            CONTINUE;
        END;

        CREATE TABLE #KeyPlan(
            KeyOrdinal int NOT NULL,
            ColumnName sysname NOT NULL,
            PRIMARY KEY(KeyOrdinal)
        );
        INSERT #KeyPlan(KeyOrdinal,ColumnName)
        SELECT ic.key_ordinal,c.name
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id=t.schema_id AND s.name='dbo'
        JOIN sys.indexes i ON i.object_id=t.object_id AND i.is_primary_key=1
        JOIN sys.index_columns ic
          ON ic.object_id=i.object_id AND ic.index_id=i.index_id
         AND ic.is_included_column=0
        JOIN sys.columns c
          ON c.object_id=t.object_id AND c.column_id=ic.column_id
        WHERE t.name=@CopyTable
          AND CHARINDEX(QUOTENAME(c.name),@CopyColumns)>0;

        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
        BEGIN
            ;WITH Candidate AS(
                SELECT i.object_id,i.index_id,
                       KeyColumns=COUNT(*)
                FROM sys.tables t
                JOIN sys.schemas s
                  ON s.schema_id=t.schema_id AND s.name='dbo'
                JOIN sys.indexes i
                  ON i.object_id=t.object_id
                 AND i.is_unique=1
                 AND i.has_filter=0
                 AND i.is_disabled=0
                JOIN sys.index_columns ic
                  ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                 AND ic.is_included_column=0
                WHERE t.name=@CopyTable
                GROUP BY i.object_id,i.index_id
            ), Chosen AS(
                SELECT TOP(1)object_id,index_id
                FROM Candidate
                ORDER BY KeyColumns,index_id
            )
            INSERT #KeyPlan(KeyOrdinal,ColumnName)
            SELECT ic.key_ordinal,c.name
            FROM Chosen x
            JOIN sys.index_columns ic
              ON ic.object_id=x.object_id AND ic.index_id=x.index_id
             AND ic.is_included_column=0
            JOIN sys.columns c
              ON c.object_id=ic.object_id AND c.column_id=ic.column_id
            WHERE CHARINDEX(QUOTENAME(c.name),@CopyColumns)>0;
        END;

        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Alerts_History_Employees'
        BEGIN
            INSERT #KeyPlan VALUES(1,'AlertsHistoryId'),(2,'EmployeeID');
            SET @UsingKeyOverride=1;
            SET @AllowDuplicateKey=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Employees_Regions'
        BEGIN
            INSERT #KeyPlan VALUES(1,'EmployeeID'),(2,'RegionID');
            SET @UsingKeyOverride=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Locations_EmployeesAtWork'
        BEGIN
            INSERT #KeyPlan VALUES(1,'LocationID'),(2,'EmployeeID');
            SET @UsingKeyOverride=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Change_Log'
        BEGIN
            INSERT #KeyPlan VALUES(1,'Change_LogID');
            SET @UsingKeyOverride=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Employees_CheckInOut'
        BEGIN
            INSERT #KeyPlan VALUES(1,'Employees_CheckInOutID');
            SET @UsingKeyOverride=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Invoice_Employees'
        BEGIN
            INSERT #KeyPlan VALUES(1,'Invoice_Employees_ID');
            SET @UsingKeyOverride=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Invoice_Payments'
        BEGIN
            INSERT #KeyPlan VALUES(1,'Invoice_Payments_ID');
            SET @UsingKeyOverride=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Refunds_Payments'
        BEGIN
            INSERT #KeyPlan VALUES(1,'Id');
            SET @UsingKeyOverride=1;
        END;
        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
           AND @CopyTable='Refunds_Products'
        BEGIN
            INSERT #KeyPlan VALUES(1,'Id');
            SET @UsingKeyOverride=1;
        END;

        IF NOT EXISTS(SELECT 1 FROM #KeyPlan)
        BEGIN
            INSERT #SkippedTables VALUES(
                @CopyTag,@CopyTable,N'no deterministic row key'
            );
            DROP TABLE #KeyPlan;
            FETCH NEXT FROM CopyCursor
            INTO @CopyTag,@CopySource,@CopyOffset,@CopyTable;
            CONTINUE;
        END;

        /*
        Rebuild only the key expressions.  This is deliberately parallel to the
        select-expression rules above so NOT EXISTS compares the actual target
        key after product mapping, fixed invoice repair, and source-B offset.
        */
        SET @KeyPredicate=N'';
        SET @KeyColumns=N'';
        SET @NullKeyPredicate=N'';
        DECLARE KeyCursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT KeyOrdinal,ColumnName FROM #KeyPlan ORDER BY KeyOrdinal;
        OPEN KeyCursor;
        FETCH NEXT FROM KeyCursor INTO @KeyOrdinal,@CurrentColumn;
        WHILE @@FETCH_STATUS=0
        BEGIN
            DECLARE @Normalized varchar(128),@IsProduct bit,@ShouldOffset bit;
            SELECT @Normalized=NormalizedName,
                   @IsProduct=IsProductReference,
                   @ShouldOffset=ShouldOffset
            FROM #ColumnRules
            WHERE TableName=@CopyTable AND ColumnName=@CurrentColumn;

            SET @CurrentExpression=N's.'+QUOTENAME(@CurrentColumn);
            IF @IsProduct=1
                SET @CurrentExpression=N'CASE WHEN s.'+
                    QUOTENAME(@CurrentColumn)+N'>0 THEN COALESCE(
                    (SELECT pm.TargetProductID FROM #ProductMap pm
                     WHERE pm.SourceTag='+QUOTENAME(@CopyTag,'''')+N'
                       AND pm.SourceProductID=s.'+
                    QUOTENAME(@CurrentColumn)+N'),
                    s.'+QUOTENAME(@CurrentColumn)+N'+'+
                    CONVERT(nvarchar(30),@CopyOffset)+N')
                    ELSE s.'+QUOTENAME(@CurrentColumn)+N' END';
            ELSE IF @CopyOffset>0 AND @ShouldOffset=1
                SET @CurrentExpression=N'CASE WHEN s.'+
                    QUOTENAME(@CurrentColumn)+N'>0
                    THEN CONVERT(bigint,s.'+QUOTENAME(@CurrentColumn)+N')+'+
                    CONVERT(nvarchar(30),@CopyOffset)+N'
                    ELSE s.'+QUOTENAME(@CurrentColumn)+N' END';

            SET @KeyPredicate+=CASE WHEN @KeyPredicate=N''
                THEN N'' ELSE N' AND ' END+
                N't.'+QUOTENAME(@CurrentColumn)+N'='+
                @CurrentExpression;
            SET @KeyColumns+=CASE WHEN @KeyColumns=N''
                THEN N'' ELSE N',' END+QUOTENAME(@CurrentColumn);
            SET @NullKeyPredicate+=CASE WHEN @NullKeyPredicate=N''
                THEN N'' ELSE N' OR ' END+
                N's.'+QUOTENAME(@CurrentColumn)+N' IS NULL';
            FETCH NEXT FROM KeyCursor INTO @KeyOrdinal,@CurrentColumn;
        END;
        CLOSE KeyCursor;
        DEALLOCATE KeyCursor;

        IF @AllowDuplicateKey=1
        BEGIN
            SET @MultiplicityColumns=@KeyColumns+N',[WasSentTo]';
            SET @MultiplicityPredicate=@KeyPredicate+N'
      AND (t.[WasSentTo]=s.[WasSentTo]
           OR (t.[WasSentTo] IS NULL AND s.[WasSentTo] IS NULL))';
        END;

        IF @UsingKeyOverride=1
        BEGIN
            SET @Sql=N'
IF EXISTS(
 SELECT 1 FROM '+QUOTENAME(@CopySource)+N'.dbo.'+
 QUOTENAME(@CopyTable)+N' s WHERE '+@NullKeyPredicate+N'
)
 THROW 53128,''A configured source row key contains null.'',1;';
            IF @AllowDuplicateKey=0
                SET @Sql+=N'
IF EXISTS(
 SELECT 1 FROM '+QUOTENAME(@CopySource)+N'.dbo.'+
 QUOTENAME(@CopyTable)+N' s
 GROUP BY '+@KeyColumns+N'
 HAVING COUNT_BIG(*)>1
)
 THROW 53129,''A configured source row key is not unique.'',1;';
            EXEC(@Sql);
        END;
        DROP TABLE #KeyPlan;

        SET @Sql=N'';
        IF @HasIdentity=1
            SET @Sql+=N'SET IDENTITY_INSERT dbo.'+
                       QUOTENAME(@CopyTable)+N' ON;';
        IF @AllowDuplicateKey=1
            SET @Sql+=N'
;WITH SourceRanked AS(
    SELECT s.*,
           ROW_NUMBER() OVER(
               PARTITION BY '+@MultiplicityColumns+N'
               ORDER BY (SELECT 0)
           ) AS __codex_occurrence_ordinal
    FROM '+QUOTENAME(@CopySource)+N'.dbo.'+
        QUOTENAME(@CopyTable)+N' s
),
TargetRanked AS(
    SELECT t.*,
           ROW_NUMBER() OVER(
               PARTITION BY '+@MultiplicityColumns+N'
               ORDER BY (SELECT 0)
           ) AS __codex_occurrence_ordinal
    FROM dbo.'+QUOTENAME(@CopyTable)+N' t
)
INSERT dbo.'+QUOTENAME(@CopyTable)+N'('+@CopyColumns+N')
SELECT '+@CopyExpressions+N'
FROM SourceRanked s
WHERE NOT EXISTS(
    SELECT 1 FROM TargetRanked t
    WHERE '+@MultiplicityPredicate+N'
      AND t.__codex_occurrence_ordinal=s.__codex_occurrence_ordinal
);
SELECT @RowsOut=@@ROWCOUNT;';
        ELSE
            SET @Sql+=N'
INSERT dbo.'+QUOTENAME(@CopyTable)+N'('+@CopyColumns+N')
SELECT '+@CopyExpressions+N'
FROM '+QUOTENAME(@CopySource)+N'.dbo.'+QUOTENAME(@CopyTable)+N' s
WHERE NOT EXISTS(
    SELECT 1 FROM dbo.'+QUOTENAME(@CopyTable)+N' t
    WHERE '+@KeyPredicate+N'
);
SELECT @RowsOut=@@ROWCOUNT;';
        IF @HasIdentity=1
            SET @Sql+=N'SET IDENTITY_INSERT dbo.'+
                       QUOTENAME(@CopyTable)+N' OFF;';
        SET @Rows=0;
        EXEC sys.sp_executesql
             @Sql,
             N'@SourceTag char(1),@RowsOut bigint OUTPUT',
             @SourceTag=@CopyTag,@RowsOut=@Rows OUTPUT;
        INSERT #CopyResults VALUES(@CopyTag,@CopyTable,@Rows);

        FETCH NEXT FROM CopyCursor
        INTO @CopyTag,@CopySource,@CopyOffset,@CopyTable;
    END;
    CLOSE CopyCursor;
    DEALLOCATE CopyCursor;

    DECLARE @RegionNameCharacters int=(
        SELECT CASE WHEN ty.name IN('nvarchar','nchar')
                    THEN c.max_length/2 ELSE c.max_length END
        FROM sys.columns c
        JOIN sys.types ty ON ty.user_type_id=c.user_type_id
        WHERE c.object_id=OBJECT_ID(N'dbo.Regions')
          AND c.name='RegionName'
    );
    IF @RegionNameCharacters IS NULL OR @RegionNameCharacters<1
        SET @RegionNameCharacters=250;
    SET @Sql=N'
UPDATE t
SET RegionName=LEFT(CONCAT(N''LE BOUTIQUE INSTYLE - '',s.RegionName),@MaxChars)
FROM dbo.Regions t
JOIN '+QUOTENAME(@SourceA)+N'.dbo.Regions s
  ON t.RegionID=s.RegionID;
UPDATE t
SET RegionName=LEFT(CONCAT(N''Instyle Fragrance - '',s.RegionName),@MaxChars)
FROM dbo.Regions t
JOIN '+QUOTENAME(@SourceB)+N'.dbo.Regions s
  ON t.RegionID=s.RegionID+@Offset;';
    EXEC sys.sp_executesql
         @Sql,N'@MaxChars int,@Offset bigint',
         @MaxChars=@RegionNameCharacters,@Offset=@SourceBOffset;

    /*
    Remap existing target product orphans to the canonical/placeholder ProductID.
    Rows inserted above already use #ProductMap; this also repairs the partial
    prior demo copy.
    */
    DECLARE RepairCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT TableName,ColumnName FROM #ProductReferencePlan;
    OPEN RepairCursor;
    FETCH NEXT FROM RepairCursor INTO @PlanTable,@PlanColumn;
    WHILE @@FETCH_STATUS=0
    BEGIN
        IF OBJECT_ID(N'dbo.'+@PlanTable,'U') IS NOT NULL
           AND COL_LENGTH(N'dbo.'+@PlanTable,@PlanColumn) IS NOT NULL
        BEGIN
            SET @Sql=N'
UPDATE x
SET '+QUOTENAME(@PlanColumn)+N'=m.TargetProductID
FROM dbo.'+QUOTENAME(@PlanTable)+N' x
LEFT JOIN dbo.Products p
  ON p.ProductID=x.'+QUOTENAME(@PlanColumn)+N'
JOIN #ProductMap m
  ON m.SourceTag=CASE
      WHEN x.'+QUOTENAME(@PlanColumn)+N'>='+
          CONVERT(nvarchar(30),@SourceBOffset)+N' THEN ''B'' ELSE ''A'' END
 AND m.SourceProductID=CONVERT(int,CASE
      WHEN x.'+QUOTENAME(@PlanColumn)+N'>='+
          CONVERT(nvarchar(30),@SourceBOffset)+N'
      THEN x.'+QUOTENAME(@PlanColumn)+N'-'+
          CONVERT(nvarchar(30),@SourceBOffset)+N'
      ELSE x.'+QUOTENAME(@PlanColumn)+N' END)
WHERE x.'+QUOTENAME(@PlanColumn)+N'>0
  AND p.ProductID IS NULL;
SELECT @RowsOut=@@ROWCOUNT;';
            SET @Rows=0;
            EXEC sys.sp_executesql
                 @Sql,N'@RowsOut bigint OUTPUT',@RowsOut=@Rows OUTPUT;
            SET @ProductReferencesRepaired+=@Rows;
        END;
        FETCH NEXT FROM RepairCursor INTO @PlanTable,@PlanColumn;
    END;
    CLOSE RepairCursor;
    DEALLOCATE RepairCursor;

    UPDATE dbo.Invoice_Products
    SET InvoiceID=CASE Invoice_Products_ID
      WHEN 1000158439 THEN 1000119342
      WHEN 1000158440 THEN 1000119343
      WHEN 1000158441 THEN 1000119343
      WHEN 1000160307 THEN 1000120626
      WHEN 1000160308 THEN 1000120626
      WHEN 1000160309 THEN 1000120627
      WHEN 1000160310 THEN 1000120628
      WHEN 1000160311 THEN 1000120629
      WHEN 1000160312 THEN 1000120630
      WHEN 1000160313 THEN 1000120631
      WHEN 1000160314 THEN 1000120631 END
    WHERE Invoice_Products_ID IN(
      1000158439,1000158440,1000158441,1000160307,1000160308,
      1000160309,1000160310,1000160311,1000160312,1000160313,
      1000160314)
      AND (InvoiceID IS NULL OR InvoiceID<>CASE Invoice_Products_ID
      WHEN 1000158439 THEN 1000119342
      WHEN 1000158440 THEN 1000119343
      WHEN 1000158441 THEN 1000119343
      WHEN 1000160307 THEN 1000120626
      WHEN 1000160308 THEN 1000120626
      WHEN 1000160309 THEN 1000120627
      WHEN 1000160310 THEN 1000120628
      WHEN 1000160311 THEN 1000120629
      WHEN 1000160312 THEN 1000120630
      WHEN 1000160313 THEN 1000120631
      WHEN 1000160314 THEN 1000120631 END);
    SET @FixedInvoiceLinksRepaired+=@@ROWCOUNT;

    UPDATE dbo.Invoice_Employees
    SET InvoiceID=CASE Invoice_Employees_ID
      WHEN 1000128329 THEN 1000119342
      WHEN 1000128330 THEN 1000119342
      WHEN 1000128331 THEN 1000119343
      WHEN 1000129823 THEN 1000120626
      WHEN 1000129824 THEN 1000120627
      WHEN 1000129825 THEN 1000120628
      WHEN 1000129826 THEN 1000120629
      WHEN 1000129827 THEN 1000120630
      WHEN 1000129828 THEN 1000120631 END
    WHERE Invoice_Employees_ID IN(
      1000128329,1000128330,1000128331,1000129823,1000129824,
      1000129825,1000129826,1000129827,1000129828)
      AND InvoiceID IS NULL;
    SET @FixedInvoiceLinksRepaired+=@@ROWCOUNT;

    UPDATE dbo.Invoice_Payments
    SET InvoiceID=CASE Invoice_Payments_ID
      WHEN 1000118824 THEN 1000119342
      WHEN 1000118825 THEN 1000119343
      WHEN 1000120135 THEN 1000120626
      WHEN 1000120136 THEN 1000120627
      WHEN 1000120137 THEN 1000120628
      WHEN 1000120138 THEN 1000120629
      WHEN 1000120139 THEN 1000120629
      WHEN 1000120140 THEN 1000120630
      WHEN 1000120141 THEN 1000120631 END
    WHERE Invoice_Payments_ID IN(
      1000118824,1000118825,1000120135,1000120136,1000120137,
      1000120138,1000120139,1000120140,1000120141)
      AND InvoiceID IS NULL;
    SET @FixedInvoiceLinksRepaired+=@@ROWCOUNT;

    /* Restore target enforcement without revalidating unrelated legacy rows. */
    DECLARE RestoreIntegrityCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT t.name
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id=t.schema_id AND s.name='dbo'
    WHERE t.is_ms_shipped=0
      AND t.name NOT LIKE '__codex[_]%';
    OPEN RestoreIntegrityCursor;
    FETCH NEXT FROM RestoreIntegrityCursor INTO @IntegrityTable;
    WHILE @@FETCH_STATUS=0
    BEGIN
        SET @Sql=N'ALTER TABLE dbo.'+QUOTENAME(@IntegrityTable)+
                 N' WITH NOCHECK CHECK CONSTRAINT ALL;';
        EXEC(@Sql);
        SET @Sql=N'ENABLE TRIGGER ALL ON dbo.'+
                 QUOTENAME(@IntegrityTable)+N';';
        EXEC(@Sql);
        FETCH NEXT FROM RestoreIntegrityCursor INTO @IntegrityTable;
    END;
    CLOSE RestoreIntegrityCursor;
    DEALLOCATE RestoreIntegrityCursor;

    /* Nova-specific final readback. */
    DECLARE @DuplicateProductKeys bigint=0,
            @ProductOrphans bigint=0,
            @BlankInvoiceProductInvoices bigint=0,
            @PlaceholderGaps bigint=0,
            @FixedRows bigint=0,
            @Locations bigint=0,
            @Regions bigint=0,
            @HistoryRows bigint=0,
            @TotalRowsInserted bigint=0,
            @ChangedTables int=0,
            @SkippedCount int=0;

    SELECT @DuplicateProductKeys=COUNT_BIG(*)
    FROM(
      SELECT
       LOWER(LTRIM(RTRIM(ISNULL(ProductName,N'')))) n,
       LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber,N''))),N' ',N'')) b1,
       LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber2,N''))),N' ',N'')) b2,
       LOWER(REPLACE(LTRIM(RTRIM(ISNULL(SKU,N''))),N' ',N'')) sku
      FROM dbo.Products
      GROUP BY
       LOWER(LTRIM(RTRIM(ISNULL(ProductName,N'')))),
       LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber,N''))),N' ',N'')),
       LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber2,N''))),N' ',N'')),
       LOWER(REPLACE(LTRIM(RTRIM(ISNULL(SKU,N''))),N' ',N''))
      HAVING COUNT_BIG(*)>1
         AND NOT(
          LOWER(LTRIM(RTRIM(ISNULL(ProductName,N''))))=N''
          AND LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber,N''))),N' ',N''))=N''
          AND LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber2,N''))),N' ',N''))=N''
          AND LOWER(REPLACE(LTRIM(RTRIM(ISNULL(SKU,N''))),N' ',N''))=N'')
    )d;

    DECLARE ValidationCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT TableName,ColumnName FROM #ProductReferencePlan;
    OPEN ValidationCursor;
    FETCH NEXT FROM ValidationCursor INTO @PlanTable,@PlanColumn;
    WHILE @@FETCH_STATUS=0
    BEGIN
        IF OBJECT_ID(N'dbo.'+@PlanTable,'U') IS NOT NULL
           AND COL_LENGTH(N'dbo.'+@PlanTable,@PlanColumn) IS NOT NULL
        BEGIN
            SET @Sql=N'
SELECT @RowsOut=COUNT_BIG(*)
FROM dbo.'+QUOTENAME(@PlanTable)+N' x
LEFT JOIN dbo.Products p
  ON p.ProductID=x.'+QUOTENAME(@PlanColumn)+N'
WHERE x.'+QUOTENAME(@PlanColumn)+N'>0
  AND p.ProductID IS NULL;';
            SET @Rows=0;
            EXEC sys.sp_executesql
                 @Sql,N'@RowsOut bigint OUTPUT',@RowsOut=@Rows OUTPUT;
            SET @ProductOrphans+=@Rows;
        END;
        FETCH NEXT FROM ValidationCursor INTO @PlanTable,@PlanColumn;
    END;
    CLOSE ValidationCursor;
    DEALLOCATE ValidationCursor;

    SELECT @BlankInvoiceProductInvoices=COUNT_BIG(*)
    FROM dbo.Invoice_Products
    WHERE InvoiceID IS NULL;
    SELECT @PlaceholderGaps=COUNT_BIG(*)
    FROM dbo.__codex_instyle_core_product_map m
    JOIN dbo.Products p ON p.ProductID=m.TargetProductID
    WHERE m.IsPlaceholder=1
      AND (NULLIF(LTRIM(RTRIM(p.ProductName)),N'') IS NULL
       OR NULLIF(LTRIM(RTRIM(p.SKU)),N'') IS NULL
       OR NULLIF(LTRIM(RTRIM(p.BarcodeNumber)),N'') IS NULL);
    SELECT @FixedRows=COUNT_BIG(*)
    FROM dbo.Invoice_Products
    WHERE (Invoice_Products_ID=1000158439 AND InvoiceID=1000119342)
       OR (Invoice_Products_ID=1000158440 AND InvoiceID=1000119343)
       OR (Invoice_Products_ID=1000158441 AND InvoiceID=1000119343)
       OR (Invoice_Products_ID=1000160307 AND InvoiceID=1000120626)
       OR (Invoice_Products_ID=1000160308 AND InvoiceID=1000120626)
       OR (Invoice_Products_ID=1000160309 AND InvoiceID=1000120627)
       OR (Invoice_Products_ID=1000160310 AND InvoiceID=1000120628)
       OR (Invoice_Products_ID=1000160311 AND InvoiceID=1000120629)
       OR (Invoice_Products_ID=1000160312 AND InvoiceID=1000120630)
       OR (Invoice_Products_ID=1000160313 AND InvoiceID=1000120631)
       OR (Invoice_Products_ID=1000160314 AND InvoiceID=1000120631);
    SELECT @Locations=COUNT_BIG(*) FROM dbo.Locations;
    SELECT @Regions=COUNT_BIG(*) FROM dbo.Regions;
    SELECT @HistoryRows=COUNT_BIG(*) FROM dbo.InventoryHistoryItem;
    SELECT @TotalRowsInserted=COALESCE(SUM(RowsInserted),0)
    FROM #CopyResults;
    SELECT @ChangedTables=COUNT(DISTINCT TableName)
    FROM #CopyResults
    WHERE RowsInserted>0;
    SELECT @SkippedCount=COUNT(*) FROM #SkippedTables;

    IF @DuplicateProductKeys<>0
        THROW 53120,'Duplicate nonblank product keys remain after the copy.',1;
    IF @ProductOrphans<>0
        THROW 53121,'Product-reference orphans remain after the copy.',1;
    IF @BlankInvoiceProductInvoices<>0
        THROW 53122,'Invoice_Products still contains blank InvoiceID values.',1;
    IF @PlaceholderGaps<>0
        THROW 53123,'An inactive missing-product row has blank required fields.',1;
    IF @FixedRows<>11
        THROW 53124,'The eleven fixed invoice-product links did not read back.',1;
    IF @Locations<>44 OR @Regions<>4
        THROW 53125,'The expected 44 locations and 4 regions did not read back.',1;
    IF @HistoryRows<@ExpectedHistoryRows
        THROW 53126,'InventoryHistoryItem copy coverage is incomplete.',1;
    IF @SkippedCount<>0
        THROW 53127,'One or more nonempty source tables lacked a deterministic copy key.',1;

    DECLARE @ResultJson nvarchar(max);
    SELECT @ResultJson=(
      SELECT
       CONVERT(nvarchar(36),@RunId) runId,
       N'single_database_side_set_based_sql' copyMode,
       DATEDIFF_BIG(millisecond,@StartedAt,SYSUTCDATETIME()) elapsedMilliseconds,
       @ProductsInserted canonicalProductsInserted,
       @PlaceholdersInserted inactivePlaceholdersInserted,
       @ProductReferencesRepaired productReferencesRepaired,
       @FixedInvoiceLinksRepaired fixedInvoiceLinksRepaired,
       @TotalRowsInserted businessRowsInserted,
       @ChangedTables changedTables,
       @HistoryRows inventoryHistoryItemRows,
       @ExpectedHistoryRows expectedInventoryHistoryItemRowsAtReadback,
       @Locations locations,
       @Regions regions,
       @DuplicateProductKeys duplicateNonblankProductKeys,
       @ProductOrphans productOrphanRows,
       @BlankInvoiceProductInvoices invoiceProductsWithBlankInvoiceId,
       @PlaceholderGaps placeholderRequiredFieldGaps,
       @FixedRows fixedInvoiceProductRows
      FOR JSON PATH,WITHOUT_ARRAY_WRAPPER
    );

    UPDATE dbo.__codex_instyle_set_based_receipts
    SET CompletedAtUtc=SYSUTCDATETIME(),
        ResultJson=@ResultJson
    WHERE IdempotencyKey=@OperatorIdempotencyKey;

    COMMIT TRANSACTION;
    SELECT ResultJson=@ResultJson;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
