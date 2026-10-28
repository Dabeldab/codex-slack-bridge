from __future__ import annotations

# AgentChat/coding_agent 2026-08-06T11:35:00Z
# AgentChat/coding_agent 2026-08-06T13:12:00Z
# AgentChat/coding_agent 2026-08-06T13:54:59Z

from .instyle_demo_merge_sql_v2 import INSTYLE_DEMO_MERGE_SQL_V2


def _replace_once(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise RuntimeError(f"reviewed Instyle SQL marker count changed: {old[:80]!r}")
    return value.replace(old, new, 1)


def _production_sql() -> str:
    """Derive the fixed production batch from the reviewed set-based demo asset."""

    sql = INSTYLE_DEMO_MERGE_SQL_V2
    sql = sql.replace("POS_DEMO_NOVA_CAFE", "POS_INSTYLE_RUNWAY")
    sql = sql.replace("DEMO_NOVA_CAFE", "INSTYLE_RUNWAY")
    sql = sql.replace(
        "__codex_instyle_core_product_map",
        "__codex_instyle_runway_product_map",
    )
    sql = sql.replace(
        "__codex_instyle_set_based_receipts",
        "__codex_instyle_runway_merge_receipts",
    )
    sql = sql.replace(
        "nova:instyle-demo:set-based-copy",
        "nova:instyle-runway:production-merge",
    )
    sql = sql.replace("fixed Instyle demo copy", "fixed Instyle Runway merge")
    sql = sql.replace("demo target", "production target")
    sql = sql.replace("fixed demo", "fixed production")

    sql = _replace_once(
        sql,
        """            KeyHash char(64) NOT NULL,
            IsPlaceholder bit NOT NULL,
            UpdatedAtUtc datetime2(7) NOT NULL,""",
        """            KeyHash char(64) NOT NULL,
            IsPlaceholder bit NOT NULL,
            PlanHash char(64) NOT NULL,
            UpdatedAtUtc datetime2(7) NOT NULL,""",
    )

    sql = _replace_once(
        sql,
        "DECLARE @ExpectedHistoryRows bigint=0;",
        """DECLARE @ExpectedHistoryRows bigint=0;
DECLARE @BackupTablesCreated int=0;
DECLARE @BackupRowsCaptured bigint=0;""",
    )

    sql = _replace_once(
        sql,
        """CREATE TABLE #SkippedTables(
    SourceTag char(1) NOT NULL,
    TableName sysname NOT NULL,
    Reason nvarchar(250) NOT NULL
);""",
        """CREATE TABLE #SkippedTables(
    SourceTag char(1) NOT NULL,
    TableName sysname NOT NULL,
    Reason nvarchar(250) NOT NULL
);

/*
The production account starts with LocationID 1-18 placeholders.  Keep the
stable source-A IDs 1-24, allocate source-B locations to 25-44, and collapse
every source region into one fixed destination region per source account.
*/
CREATE TABLE #LocationMap(
    SourceTag char(1) NOT NULL,
    SourceLocationID int NOT NULL,
    TargetLocationID int NOT NULL,
    TargetRegionID int NOT NULL,
    PRIMARY KEY(SourceTag,SourceLocationID),
    UNIQUE(TargetLocationID)
);
CREATE TABLE #RegionMap(
    SourceTag char(1) NOT NULL,
    SourceRegionID int NOT NULL,
    TargetRegionID int NOT NULL,
    PRIMARY KEY(SourceTag,SourceRegionID)
);

SET @Sql=N'
INSERT #LocationMap(SourceTag,SourceLocationID,TargetLocationID,TargetRegionID)
SELECT ''A'',LocationID,LocationID,1
FROM '+QUOTENAME(@SourceA)+N'.dbo.Locations;
INSERT #LocationMap(SourceTag,SourceLocationID,TargetLocationID,TargetRegionID)
SELECT ''B'',LocationID,LocationID+24,2
FROM '+QUOTENAME(@SourceB)+N'.dbo.Locations;
INSERT #RegionMap(SourceTag,SourceRegionID,TargetRegionID)
SELECT ''A'',RegionID,1 FROM '+QUOTENAME(@SourceA)+N'.dbo.Regions;
INSERT #RegionMap(SourceTag,SourceRegionID,TargetRegionID)
SELECT ''B'',RegionID,2 FROM '+QUOTENAME(@SourceB)+N'.dbo.Regions;';
EXEC(@Sql);

IF (SELECT COUNT_BIG(*) FROM #LocationMap WHERE SourceTag='A')<>24
   OR (SELECT COUNT_BIG(*) FROM #LocationMap WHERE SourceTag='B')<>20
   OR (SELECT COUNT_BIG(*) FROM #LocationMap)<>44
   OR (SELECT MIN(TargetLocationID) FROM #LocationMap)<>1
   OR (SELECT MAX(TargetLocationID) FROM #LocationMap)<>44
   OR (SELECT COUNT_BIG(DISTINCT TargetLocationID) FROM #LocationMap)<>44
    THROW 53201,'The reviewed 24/20 source location map changed.',1;
IF NOT EXISTS(SELECT 1 FROM #RegionMap WHERE SourceTag='A')
   OR NOT EXISTS(SELECT 1 FROM #RegionMap WHERE SourceTag='B')
    THROW 53202,'One of the fixed source region sets is unavailable.',1;""",
    )

    sql = _replace_once(
        sql,
        """    /* Disable enforcement only inside this target transaction. */""",
        """    /*
    Preserve a complete row backup of every production business table before
    the first permanent business write.  The backup tables and manifest remain
    in the target after commit and are never cleaned up by this operation.
    */
    IF OBJECT_ID(N'dbo.__codex_instyle_runway_backup_manifest','U') IS NULL
    BEGIN
        CREATE TABLE dbo.__codex_instyle_runway_backup_manifest(
            PlanHash char(64) NOT NULL,
            IdempotencyKey nvarchar(200) NOT NULL,
            SourceTable sysname NOT NULL,
            BackupTable sysname NOT NULL,
            SourceRows bigint NOT NULL,
            BackupRows bigint NOT NULL,
            CreatedAtUtc datetime2(7) NOT NULL,
            CONSTRAINT PK___codex_instyle_runway_backup_manifest
                PRIMARY KEY(PlanHash,SourceTable)
        );
    END;

    DECLARE @BackupSourceTable sysname,@BackupTable sysname,
            @BackupSourceRows bigint,@BackupRows bigint;
    DECLARE BackupCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT t.name
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id=t.schema_id AND s.name='dbo'
    WHERE t.is_ms_shipped=0
      AND t.name<>N'Log4Net'
      AND t.name NOT LIKE N'__codex[_]%'
      AND t.name NOT LIKE N'__nova[_]%'
    ORDER BY t.name;
    OPEN BackupCursor;
    FETCH NEXT FROM BackupCursor INTO @BackupSourceTable;
    WHILE @@FETCH_STATUS=0
    BEGIN
        SET @BackupTable=LEFT(
            N'__codex_bak_runway_'+LEFT(@OperatorPlanHash,12)+N'_'+
            @BackupSourceTable,128
        );
        IF OBJECT_ID(N'dbo.'+@BackupTable,'U') IS NOT NULL
            THROW 53203,'A production backup table already exists for this plan.',1;
        SET @Sql=N'SELECT @RowsOut=COUNT_BIG(*) FROM dbo.'+
                 QUOTENAME(@BackupSourceTable)+N';';
        SET @BackupSourceRows=0;
        EXEC sys.sp_executesql @Sql,N'@RowsOut bigint OUTPUT',
             @RowsOut=@BackupSourceRows OUTPUT;
        SET @Sql=N'SELECT * INTO dbo.'+QUOTENAME(@BackupTable)+
                 N' FROM dbo.'+QUOTENAME(@BackupSourceTable)+N';'+
                 N'SELECT @RowsOut=COUNT_BIG(*) FROM dbo.'+
                 QUOTENAME(@BackupTable)+N';';
        SET @BackupRows=0;
        EXEC sys.sp_executesql @Sql,N'@RowsOut bigint OUTPUT',
             @RowsOut=@BackupRows OUTPUT;
        IF @BackupRows<>@BackupSourceRows
            THROW 53204,'A production backup row count did not read back.',1;
        INSERT dbo.__codex_instyle_runway_backup_manifest(
            PlanHash,IdempotencyKey,SourceTable,BackupTable,
            SourceRows,BackupRows,CreatedAtUtc
        ) VALUES(
            @OperatorPlanHash,@OperatorIdempotencyKey,@BackupSourceTable,
            @BackupTable,@BackupSourceRows,@BackupRows,SYSUTCDATETIME()
        );
        SET @BackupTablesCreated+=1;
        SET @BackupRowsCaptured+=@BackupRows;
        FETCH NEXT FROM BackupCursor INTO @BackupSourceTable;
    END;
    CLOSE BackupCursor;
    DEALLOCATE BackupCursor;
    IF @BackupTablesCreated=0
        THROW 53205,'No production target tables were backed up.',1;

    /* Persist the full eleven-row invoice-less quarantine inside the target. */
    IF OBJECT_ID(N'dbo.__codex_instyle_runway_invoice_product_quarantine','U') IS NULL
    BEGIN
        CREATE TABLE dbo.__codex_instyle_runway_invoice_product_quarantine(
            SourceTag char(1) NOT NULL,
            SourceInvoiceProductID int NOT NULL,
            SourceInvoiceID int NULL,
            SourceProductID int NULL,
            RowJson nvarchar(max) NOT NULL,
            PlanHash char(64) NOT NULL,
            QuarantinedAtUtc datetime2(7) NOT NULL,
            CONSTRAINT PK___codex_instyle_runway_invoice_product_quarantine
                PRIMARY KEY(SourceTag,SourceInvoiceProductID)
        );
    END;
    SET @Sql=N'
INSERT dbo.__codex_instyle_runway_invoice_product_quarantine(
 SourceTag,SourceInvoiceProductID,SourceInvoiceID,SourceProductID,
 RowJson,PlanHash,QuarantinedAtUtc)
SELECT @Tag,ip.Invoice_Products_ID,ip.InvoiceID,ip.ProductID,
       (SELECT ip.* FOR JSON PATH,WITHOUT_ARRAY_WRAPPER),
       @PlanHash,SYSUTCDATETIME()
FROM '+QUOTENAME(@SourceA)+N'.dbo.Invoice_Products ip
LEFT JOIN '+QUOTENAME(@SourceA)+N'.dbo.Invoices i ON i.InvoiceID=ip.InvoiceID
WHERE (ip.InvoiceID IS NULL OR i.InvoiceID IS NULL)
  AND NOT EXISTS(
      SELECT 1 FROM dbo.__codex_instyle_runway_invoice_product_quarantine q
      WHERE q.SourceTag=@Tag
        AND q.SourceInvoiceProductID=ip.Invoice_Products_ID
  );';
    EXEC sys.sp_executesql @Sql,N'@Tag char(1),@PlanHash char(64)',
         @Tag='A',@PlanHash=@OperatorPlanHash;
    SET @Sql=REPLACE(@Sql,QUOTENAME(@SourceA),QUOTENAME(@SourceB));
    EXEC sys.sp_executesql @Sql,N'@Tag char(1),@PlanHash char(64)',
         @Tag='B',@PlanHash=@OperatorPlanHash;
    IF (SELECT COUNT_BIG(*)
        FROM dbo.__codex_instyle_runway_invoice_product_quarantine
        WHERE PlanHash=@OperatorPlanHash)<>11
        THROW 53206,'The eleven-row production quarantine did not read back.',1;

    /* Disable enforcement only inside this target transaction. */""",
    )

    sql = _replace_once(
        sql,
        """    Copy every other compatible business table.  One INSERT ... SELECT runs per
    source/table and checks the transformed target key, so reruns insert only
    missing rows.  Log4Net and the broker's own helper tables are intentionally
    excluded; InventoryHistoryItem is included.
    */""",
        """    Build the two fixed production regions before location and relationship
    rows are upserted.  Region 1 owns source A and Region 2 owns source B.
    */
    UPDATE t
    SET RegionName=N'LE BOUTIQUE INSTYLE',
        RegionManagerEmployeeID=s.RegionManagerEmployeeID,
        RegionManagerCommissionPercent=s.RegionManagerCommissionPercent,
        UseKits=s.UseKits,
        Version=s.Version
    FROM dbo.Regions t
    CROSS JOIN(
        SELECT TOP(1) RegionManagerEmployeeID,
               RegionManagerCommissionPercent,UseKits,Version
        FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Regions
        ORDER BY RegionID
    )s
    WHERE t.RegionID=1;
    IF @@ROWCOUNT<>1
        THROW 53207,'The production Region 1 scaffold changed.',1;

    SET IDENTITY_INSERT dbo.Regions ON;
    INSERT dbo.Regions(
        RegionID,RegionName,RegionManagerEmployeeID,
        RegionManagerCommissionPercent,UseKits,Version
    )

    SELECT 2,N'Instyle Fragrance',
           CASE WHEN RegionManagerEmployeeID>0
                THEN RegionManagerEmployeeID+1000000000
                ELSE RegionManagerEmployeeID END,
           RegionManagerCommissionPercent,UseKits,Version
    FROM [POS_Instyle_Fragrance].dbo.Regions s
    WHERE s.RegionID=(SELECT MIN(RegionID)
                      FROM [POS_Instyle_Fragrance].dbo.Regions)
      AND NOT EXISTS(SELECT 1 FROM dbo.Regions WHERE RegionID=2);
    SET IDENTITY_INSERT dbo.Regions OFF;
    UPDATE t
    SET RegionName=N'Instyle Fragrance',
        RegionManagerEmployeeID=CASE WHEN s.RegionManagerEmployeeID>0
             THEN s.RegionManagerEmployeeID+1000000000
             ELSE s.RegionManagerEmployeeID END,
        RegionManagerCommissionPercent=s.RegionManagerCommissionPercent,
        UseKits=s.UseKits,
        Version=s.Version
    FROM dbo.Regions t
    CROSS JOIN(
        SELECT TOP(1) RegionManagerEmployeeID,
               RegionManagerCommissionPercent,UseKits,Version
        FROM [POS_Instyle_Fragrance].dbo.Regions
        ORDER BY RegionID
    )s
    WHERE t.RegionID=2;
    IF @@ROWCOUNT<>1
        THROW 53208,'The production Region 2 row did not read back.',1;

    /* Employees_Regions has no declared key; collapse it explicitly. */
    INSERT dbo.Employees_Regions(EmployeeID,RegionID)
    SELECT DISTINCT er.EmployeeID,1
    FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Employees_Regions er
    WHERE er.EmployeeID>0
      AND NOT EXISTS(
          SELECT 1 FROM dbo.Employees_Regions t
          WHERE t.EmployeeID=er.EmployeeID AND t.RegionID=1
      );
    INSERT dbo.Employees_Regions(EmployeeID,RegionID)
    SELECT DISTINCT er.EmployeeID+1000000000,2
    FROM [POS_Instyle_Fragrance].dbo.Employees_Regions er
    WHERE er.EmployeeID>0
      AND NOT EXISTS(
          SELECT 1 FROM dbo.Employees_Regions t
          WHERE t.EmployeeID=er.EmployeeID+1000000000 AND t.RegionID=2
      );

    /*
    Copy every other compatible business table with source-qualified location,
    region, and product mappings.  Existing scaffold keys are updated in place;
    missing transformed keys are inserted.
    */""",
    )

    sql = _replace_once(
        sql,
        """    UPDATE persisted
    SET persisted.TargetProductID=m.TargetProductID,
        persisted.KeyHash=LOWER(CONVERT(char(64),m.KeyHash,2)),
        persisted.IsPlaceholder=m.IsPlaceholder,
        persisted.UpdatedAtUtc=SYSUTCDATETIME()
    FROM dbo.__codex_instyle_runway_product_map persisted
    JOIN #ProductMap m
      ON m.SourceTag=persisted.SourceTag
     AND m.SourceProductID=persisted.SourceProductID;

    UPDATE persisted
    SET persisted.IsPlaceholder=0,
        persisted.UpdatedAtUtc=SYSUTCDATETIME()
    FROM dbo.__codex_instyle_runway_product_map persisted
    WHERE persisted.IsPlaceholder=1
      AND NOT EXISTS(
          SELECT 1 FROM #ProductMap m
          WHERE m.SourceTag=persisted.SourceTag
            AND m.SourceProductID=persisted.SourceProductID
            AND m.IsPlaceholder=1
      );

    INSERT dbo.__codex_instyle_runway_product_map(
        SourceTag,SourceProductID,TargetProductID,
        KeyHash,IsPlaceholder,UpdatedAtUtc
    )
    SELECT m.SourceTag,m.SourceProductID,m.TargetProductID,
           LOWER(CONVERT(char(64),m.KeyHash,2)),
           m.IsPlaceholder,SYSUTCDATETIME()
    FROM #ProductMap m
    WHERE NOT EXISTS(
        SELECT 1 FROM dbo.__codex_instyle_runway_product_map persisted
        WHERE persisted.SourceTag=m.SourceTag
          AND persisted.SourceProductID=m.SourceProductID
    );""",
        """    /* The durable source-qualified product crosswalk is immutable. */
    IF EXISTS(SELECT 1 FROM dbo.__codex_instyle_runway_product_map)
       AND EXISTS(
        SELECT 1
        FROM dbo.__codex_instyle_runway_product_map persisted
        FULL JOIN #ProductMap m
          ON m.SourceTag=persisted.SourceTag
         AND m.SourceProductID=persisted.SourceProductID
        WHERE persisted.SourceTag IS NULL OR m.SourceTag IS NULL
           OR persisted.TargetProductID<>m.TargetProductID
           OR persisted.KeyHash<>LOWER(CONVERT(char(64),m.KeyHash,2))
           OR persisted.IsPlaceholder<>m.IsPlaceholder
           OR persisted.PlanHash<>@OperatorPlanHash
    )
        THROW 53211,'The immutable production product crosswalk changed.',1;

    INSERT dbo.__codex_instyle_runway_product_map(
        SourceTag,SourceProductID,TargetProductID,
        KeyHash,IsPlaceholder,PlanHash,UpdatedAtUtc
    )
    SELECT m.SourceTag,m.SourceProductID,m.TargetProductID,
           LOWER(CONVERT(char(64),m.KeyHash,2)),
           m.IsPlaceholder,@OperatorPlanHash,SYSUTCDATETIME()
    FROM #ProductMap m
    WHERE NOT EXISTS(
        SELECT 1 FROM dbo.__codex_instyle_runway_product_map persisted
        WHERE persisted.SourceTag=m.SourceTag
          AND persisted.SourceProductID=m.SourceProductID
    );""",
    )

    sql = _replace_once(
        sql,
        """      N''Products'',N''Log4Net'',""",
        """      N''Products'',N''Regions'',N''Employees_Regions'',N''Log4Net'',""",
    )

    # The production merge intentionally copies business data, never stored
    # authentication material.  Exclude both known credential-bearing table
    # families and protected columns discovered dynamically by normalized name.
    sql = _replace_once(
        sql,
        """  AND st.name NOT LIKE N''__nova[_]%''
  AND EXISTS(""",
        """  AND st.name NOT LIKE N''__nova[_]%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%credential%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%password%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%secret%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%token%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%auth%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%session%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%paymentprofile%''
  AND LOWER(REPLACE(REPLACE(REPLACE(st.name,N''_'',N''''),N''-'',N''''),N'' '',N'''')) NOT LIKE N''%merchantcredential%''
  AND EXISTS(""",
    )

    sql = _replace_once(
        sql,
        """ SELECT tc.column_id,tc.name,tc.is_identity,
        r.IsProductReference,r.ShouldOffset""",
        """ SELECT tc.column_id,tc.name,tc.is_identity,
        r.NormalizedName,r.IsProductReference,r.ShouldOffset""",
    )
    protected_column_marker = """   AND tt.name NOT IN(N''timestamp'',N''rowversion'')
   AND (tt.name NOT IN("""
    protected_column_gate = """   AND tt.name NOT IN(N''timestamp'',N''rowversion'')
   AND r.NormalizedName NOT LIKE N''%password%''
   AND r.NormalizedName NOT LIKE N''%passcode%''
   AND r.NormalizedName NOT LIKE N''%secret%''
   AND r.NormalizedName NOT LIKE N''%securitykey%''
   AND r.NormalizedName NOT LIKE N''%apikey%''
   AND r.NormalizedName NOT LIKE N''%token%''
   AND r.NormalizedName NOT LIKE N''%authorization%''
   AND r.NormalizedName NOT LIKE N''%cookie%''
   AND r.NormalizedName NOT LIKE N''%deviceconfig%''
   AND r.NormalizedName NOT LIKE N''%merchantnumber%''
   AND r.NormalizedName NOT LIKE N''%merchanttransid%''
   AND r.NormalizedName NOT LIKE N''%merchantloginid%''
   AND r.NormalizedName NOT LIKE N''%employeessn%''
   AND r.NormalizedName NOT LIKE N''%cardnumber%''
   AND r.NormalizedName NOT LIKE N''%cvv%''
   AND r.NormalizedName NOT LIKE N''%trackdata%''
   AND (tt.name NOT IN("""
    if sql.count(protected_column_marker) != 2:
        raise RuntimeError("reviewed Instyle protected-column marker count changed")
    sql = sql.replace(protected_column_marker, protected_column_gate)

    location_expression = """    WHEN cc.NormalizedName LIKE N''%locationid'' THEN CONCAT(
      N''CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN COALESCE(
          (SELECT lm.TargetLocationID FROM #LocationMap lm
           WHERE lm.SourceTag=@SourceTag
             AND lm.SourceLocationID=s.'',QUOTENAME(cc.name),
      N''),s.'',QUOTENAME(cc.name),
      N'') ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN cc.NormalizedName LIKE N''%regionid'' THEN CONCAT(
      N''CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN COALESCE(
          (SELECT rm.TargetRegionID FROM #RegionMap rm
           WHERE rm.SourceTag=@SourceTag
             AND rm.SourceRegionID=s.'',QUOTENAME(cc.name),
      N''),s.'',QUOTENAME(cc.name),
      N'') ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN @TableName=N''Locations''
         AND cc.NormalizedName=N''locationmanageremployeeid''
         AND @Offset>0 THEN CONCAT(
      N''CASE WHEN s.'',QUOTENAME(cc.name),
      N''=1 THEN CONVERT(bigint,1) WHEN s.'',QUOTENAME(cc.name),
      N''>1 THEN CONVERT(bigint,s.'',QUOTENAME(cc.name),N'')+'',
      CONVERT(nvarchar(30),@Offset),
      N'' ELSE s.'',QUOTENAME(cc.name),N'' END'')
"""
    sql = _replace_once(
        sql,
        """   CASE
    WHEN cc.IsProductReference=1 THEN CONCAT(""",
        """   CASE
""" + location_expression + """    WHEN cc.IsProductReference=1 THEN CONCAT(""",
    )

    sql = _replace_once(
        sql,
        """            @CopyTable sysname,@CopyColumns nvarchar(max),
            @CopyExpressions nvarchar(max),@KeyPredicate nvarchar(max),""",
        """            @CopyTable sysname,@CopyColumns nvarchar(max),
            @CopyExpressions nvarchar(max),@UpdateAssignments nvarchar(max),
            @KeyPredicate nvarchar(max),""",
    )
    sql = _replace_once(
        sql,
        """        SET @CopyExpressions=NULL;
        SET @KeyPredicate=NULL;""",
        """        SET @CopyExpressions=NULL;
        SET @UpdateAssignments=NULL;
        SET @KeyPredicate=NULL;""",
    )

    # The concatenation shape for assignments is easier to keep explicit than
    # trying to split the already-rendered insert column/expression lists.
    update_select = """
 @UpdateAssignments=STUFF((
   SELECT N'',''+CONVERT(nvarchar(max),
   CASE
    WHEN cc.is_identity=1 THEN NULL
    WHEN cc.NormalizedName LIKE N''%locationid'' THEN CONCAT(
      N''t.'',QUOTENAME(cc.name),N''=CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN COALESCE(
          (SELECT lm.TargetLocationID FROM #LocationMap lm
           WHERE lm.SourceTag=@SourceTag
             AND lm.SourceLocationID=s.'',QUOTENAME(cc.name),
      N''),s.'',QUOTENAME(cc.name),
      N'') ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN cc.NormalizedName LIKE N''%regionid'' THEN CONCAT(
      N''t.'',QUOTENAME(cc.name),N''=CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN COALESCE(
          (SELECT rm.TargetRegionID FROM #RegionMap rm
           WHERE rm.SourceTag=@SourceTag
             AND rm.SourceRegionID=s.'',QUOTENAME(cc.name),
      N''),s.'',QUOTENAME(cc.name),
      N'') ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN @TableName=N''Locations''
         AND cc.NormalizedName=N''locationmanageremployeeid''
         AND @Offset>0 THEN CONCAT(
      N''t.'',QUOTENAME(cc.name),N''=CASE WHEN s.'',QUOTENAME(cc.name),
      N''=1 THEN CONVERT(bigint,1) WHEN s.'',QUOTENAME(cc.name),
      N''>1 THEN CONVERT(bigint,s.'',QUOTENAME(cc.name),N'')+'',
      CONVERT(nvarchar(30),@Offset),
      N'' ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN cc.IsProductReference=1 THEN CONCAT(
      N''t.'',QUOTENAME(cc.name),N''=CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN COALESCE(
          (SELECT pm.TargetProductID FROM #ProductMap pm
           WHERE pm.SourceTag=@SourceTag
             AND pm.SourceProductID=s.'',QUOTENAME(cc.name),
      N''),CONVERT(bigint,s.'',QUOTENAME(cc.name),N'')+'',
      CONVERT(nvarchar(30),@Offset),N''-2000000000'',
      N'') ELSE s.'',QUOTENAME(cc.name),N'' END'')
    WHEN @Offset>0 AND cc.ShouldOffset=1 THEN CONCAT(
      N''t.'',QUOTENAME(cc.name),N''=CASE WHEN s.'',QUOTENAME(cc.name),
      N''>0 THEN CONVERT(bigint,s.'',QUOTENAME(cc.name),
      N'')+'',CONVERT(nvarchar(30),@Offset),
      N'' ELSE s.'',QUOTENAME(cc.name),N'' END'')
    ELSE N''t.''+QUOTENAME(cc.name)+N''=s.''+QUOTENAME(cc.name)
   END)
   FROM CompatibleColumns cc
   WHERE cc.is_identity=0
   ORDER BY cc.column_id
   FOR XML PATH(N''''),TYPE
 ).value(N''.'',N''nvarchar(max)''),1,1,N''''),
"""
    sql = _replace_once(
        sql,
        """ @HasIdentity=(
   SELECT CONVERT(bit,MAX(CONVERT(int,cc.is_identity)))
   FROM CompatibleColumns cc
 );';""",
        update_select + """ @HasIdentity=(
   SELECT CONVERT(bit,MAX(CONVERT(int,cc.is_identity)))
   FROM CompatibleColumns cc
 );';""",
    )
    sql = _replace_once(
        sql,
        """               @Columns nvarchar(max) OUTPUT,
               @Expressions nvarchar(max) OUTPUT,
               @HasIdentity bit OUTPUT',""",
        """               @Columns nvarchar(max) OUTPUT,
               @Expressions nvarchar(max) OUTPUT,
               @UpdateAssignments nvarchar(max) OUTPUT,
               @HasIdentity bit OUTPUT',""",
    )
    sql = _replace_once(
        sql,
        """             @Columns=@CopyColumns OUTPUT,
             @Expressions=@CopyExpressions OUTPUT,
             @HasIdentity=@HasIdentity OUTPUT;""",
        """             @Columns=@CopyColumns OUTPUT,
             @Expressions=@CopyExpressions OUTPUT,
             @UpdateAssignments=@UpdateAssignments OUTPUT,
             @HasIdentity=@HasIdentity OUTPUT;""",
    )

    sql = _replace_once(
        sql,
        """            IF @IsProduct=1
                SET @CurrentExpression=""",
        """            IF @Normalized LIKE '%locationid'
                SET @CurrentExpression=N'CASE WHEN s.'+
                    QUOTENAME(@CurrentColumn)+N'>0 THEN COALESCE(
                    (SELECT lm.TargetLocationID FROM #LocationMap lm
                     WHERE lm.SourceTag='+QUOTENAME(@CopyTag,'''')+N'
                       AND lm.SourceLocationID=s.'+
                    QUOTENAME(@CurrentColumn)+N'),s.'+
                    QUOTENAME(@CurrentColumn)+N') ELSE s.'+
                    QUOTENAME(@CurrentColumn)+N' END';
            ELSE IF @Normalized LIKE '%regionid'
                SET @CurrentExpression=N'CASE WHEN s.'+
                    QUOTENAME(@CurrentColumn)+N'>0 THEN COALESCE(
                    (SELECT rm.TargetRegionID FROM #RegionMap rm
                     WHERE rm.SourceTag='+QUOTENAME(@CopyTag,'''')+N'
                       AND rm.SourceRegionID=s.'+
                    QUOTENAME(@CurrentColumn)+N'),s.'+
                    QUOTENAME(@CurrentColumn)+N') ELSE s.'+
                    QUOTENAME(@CurrentColumn)+N' END';
            ELSE IF @IsProduct=1
                SET @CurrentExpression=""",
    )

    sql = _replace_once(
        sql,
        """        DROP TABLE #KeyPlan;

        SET @Sql=N'';""",
        """        IF @AllowDuplicateKey=0
           AND NULLIF(@UpdateAssignments,N'') IS NOT NULL
        BEGIN
            SET @Sql=N'UPDATE t SET '+@UpdateAssignments+N'
FROM dbo.'+QUOTENAME(@CopyTable)+N' t
JOIN '+QUOTENAME(@CopySource)+N'.dbo.'+QUOTENAME(@CopyTable)+N' s
  ON '+@KeyPredicate+N'
WHERE '+@SourceScopePredicate+N';';
            EXEC sys.sp_executesql @Sql,N'@SourceTag char(1)',
                 @SourceTag=@CopyTag;
        END;
        DROP TABLE #KeyPlan;

        SET @Sql=N'';""",
    )

    # The source-aware region names above replace the four-region demo rename.
    start = """    DECLARE @RegionNameCharacters int=("""
    end = """         @MaxChars=@RegionNameCharacters,@Offset=@SourceBOffset;
"""
    if sql.count(start) != 1 or sql.count(end) != 1:
        raise RuntimeError("reviewed region rename markers changed")
    before, tail = sql.split(start, 1)
    _, after = tail.split(end, 1)
    sql = before + after

    sql = _replace_once(sql, "@Regions<>4", "@Regions<>2")
    sql = _replace_once(
        sql,
        "The expected 44 locations and 4 regions did not read back.",
        "The expected 44 locations and 2 regions did not read back.",
    )

    sql = _replace_once(
        sql,
        """            @Regions bigint=0,
            @HistoryRows bigint=0,""",
        """            @Regions bigint=0,
            @LocationGroupMismatches bigint=0,
            @RegionGroupMismatches bigint=0,
            @DeclaredForeignKeyOrphans bigint=0,
            @HistoryRows bigint=0,""",
    )
    sql = _replace_once(
        sql,
        """    SELECT @Regions=COUNT_BIG(*) FROM dbo.Regions;
    SELECT @HistoryRows=COUNT_BIG(*) FROM dbo.InventoryHistoryItem;""",
        """    SELECT @Regions=COUNT_BIG(*) FROM dbo.Regions;
    SELECT @RegionGroupMismatches=COUNT_BIG(*)
    FROM dbo.Regions
    WHERE (RegionID=1 AND RegionName<>N'LE BOUTIQUE INSTYLE')
       OR (RegionID=2 AND RegionName<>N'Instyle Fragrance')
       OR RegionID NOT IN(1,2);
    SET @Sql=N'SELECT @RowsOut=
      (SELECT COUNT_BIG(*)
       FROM '+QUOTENAME(@SourceA)+N'.dbo.Locations s
       LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID
       WHERE t.LocationID IS NULL OR t.RegionID<>1
          OR ISNULL(t.LocationName,N'''')<>ISNULL(s.LocationName,N'''')
          OR ISNULL(t.LocationManagerEmployeeID,-2147483648)
             <>ISNULL(s.LocationManagerEmployeeID,-2147483648))+
      (SELECT COUNT_BIG(*)
       FROM '+QUOTENAME(@SourceB)+N'.dbo.Locations s
       LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID+24
       WHERE t.LocationID IS NULL OR t.RegionID<>2
          OR ISNULL(t.LocationName,N'''')<>ISNULL(s.LocationName,N'''')
          OR ISNULL(t.LocationManagerEmployeeID,-2147483648)
             <>ISNULL(CASE WHEN s.LocationManagerEmployeeID=1 THEN 1
                           WHEN s.LocationManagerEmployeeID>1
                             THEN s.LocationManagerEmployeeID+1000000000
                           ELSE s.LocationManagerEmployeeID END,-2147483648));';
    EXEC sys.sp_executesql @Sql,N'@RowsOut bigint OUTPUT',
         @RowsOut=@LocationGroupMismatches OUTPUT;

    DECLARE @FkName sysname,@FkChild sysname,@FkParent sysname,
            @FkJoin nvarchar(max),@FkRequired nvarchar(max),
            @FkPresence nvarchar(max),@FkRows bigint;
    DECLARE ForeignKeyCursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT fk.name,ct.name,pt.name,
      STUFF((SELECT N' AND p.'+QUOTENAME(pc.name)+N'=c.'+QUOTENAME(cc.name)
             FROM sys.foreign_key_columns fkc2
             JOIN sys.columns cc ON cc.object_id=fkc2.parent_object_id
                                AND cc.column_id=fkc2.parent_column_id
             JOIN sys.columns pc ON pc.object_id=fkc2.referenced_object_id
                                AND pc.column_id=fkc2.referenced_column_id
             WHERE fkc2.constraint_object_id=fk.object_id
             ORDER BY fkc2.constraint_column_id
             FOR XML PATH(N''),TYPE).value(N'.',N'nvarchar(max)'),1,5,N''),
      STUFF((SELECT N' AND c.'+QUOTENAME(cc.name)+N' IS NOT NULL'
             FROM sys.foreign_key_columns fkc2
             JOIN sys.columns cc ON cc.object_id=fkc2.parent_object_id
                                AND cc.column_id=fkc2.parent_column_id
             WHERE fkc2.constraint_object_id=fk.object_id
             ORDER BY fkc2.constraint_column_id
             FOR XML PATH(N''),TYPE).value(N'.',N'nvarchar(max)'),1,5,N''),
      N'p.'+QUOTENAME(MIN(pc.name))+N' IS NULL'
    FROM sys.foreign_keys fk
    JOIN sys.tables ct ON ct.object_id=fk.parent_object_id
    JOIN sys.tables pt ON pt.object_id=fk.referenced_object_id
    JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
    JOIN sys.columns pc ON pc.object_id=fkc.referenced_object_id
                       AND pc.column_id=fkc.referenced_column_id
    WHERE fk.is_disabled=0 AND fk.is_ms_shipped=0
      AND NOT EXISTS(
          SELECT 1
          FROM sys.foreign_key_columns fx
          JOIN sys.columns cx ON cx.object_id=fx.parent_object_id
                             AND cx.column_id=fx.parent_column_id
          WHERE fx.constraint_object_id=fk.object_id
            AND pt.name='Products'
            AND EXISTS(
                SELECT 1 FROM #ProductReferencePlan pr
                WHERE pr.TableName=ct.name AND pr.ColumnName=cx.name
            )
      )
    GROUP BY fk.object_id,fk.name,ct.name,pt.name;
    OPEN ForeignKeyCursor;
    FETCH NEXT FROM ForeignKeyCursor
    INTO @FkName,@FkChild,@FkParent,@FkJoin,@FkRequired,@FkPresence;
    WHILE @@FETCH_STATUS=0
    BEGIN
        SET @Sql=N'SELECT @RowsOut=COUNT_BIG(*) FROM dbo.'+
          QUOTENAME(@FkChild)+N' c LEFT JOIN dbo.'+QUOTENAME(@FkParent)+
          N' p ON '+@FkJoin+N' WHERE '+@FkRequired+N' AND '+@FkPresence+N';';
        SET @FkRows=0;
        EXEC sys.sp_executesql @Sql,N'@RowsOut bigint OUTPUT',
             @RowsOut=@FkRows OUTPUT;
        SET @DeclaredForeignKeyOrphans+=@FkRows;
        FETCH NEXT FROM ForeignKeyCursor
        INTO @FkName,@FkChild,@FkParent,@FkJoin,@FkRequired,@FkPresence;
    END;
    CLOSE ForeignKeyCursor;
    DEALLOCATE ForeignKeyCursor;
    SELECT @HistoryRows=COUNT_BIG(*) FROM dbo.InventoryHistoryItem;""",
    )
    sql = _replace_once(
        sql,
        """    IF @HistoryRows<@ExpectedHistoryRows
        THROW 53126,'InventoryHistoryItem copy coverage is incomplete.',1;""",
        """    IF @LocationGroupMismatches<>0 OR @RegionGroupMismatches<>0
        THROW 53209,'The source-qualified location/region map did not read back.',1;
    IF @DeclaredForeignKeyOrphans<>0
        THROW 53210,'Declared relationship orphans remain after the merge.',1;
    IF @HistoryRows<>@ExpectedHistoryRows
        THROW 53126,'InventoryHistoryItem copy coverage is not exact.',1;""",
    )
    sql = _replace_once(
        sql,
        """       @QuarantinedInvoiceProductRows quarantinedInvoiceProductRows
      FOR JSON PATH,WITHOUT_ARRAY_WRAPPER""",
        """       @QuarantinedInvoiceProductRows quarantinedInvoiceProductRows,
       @BackupTablesCreated backupTablesCreated,
       @BackupRowsCaptured backupRowsCaptured,
       @LocationGroupMismatches locationGroupMismatches,
       @RegionGroupMismatches regionGroupMismatches,
       @DeclaredForeignKeyOrphans declaredForeignKeyOrphans
      FOR JSON PATH,WITHOUT_ARRAY_WRAPPER""",
    )

    if "POS_DEMO_NOVA_CAFE" in sql or "DEMO_NOVA_CAFE" in sql:
        raise RuntimeError("production SQL still contains the demo target")
    return sql


INSTYLE_RUNWAY_MERGE_SQL_V1 = _production_sql()


INSTYLE_RUNWAY_LOCATION_STATUS_REPAIR_SQL_V2 = r"""
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME()<>N'POS_INSTYLE_RUNWAY'
    THROW 53301,'The connection is not bound to the fixed production target.',1;
IF @Apply<>1
    THROW 53302,'The fixed location-status repair requires apply mode.',1;
IF DB_ID(N'POS_LE_BOUTIQUE_INSTYLE') IS NULL
   OR DB_ID(N'POS_Instyle_Fragrance') IS NULL
   OR HAS_DBACCESS(N'POS_LE_BOUTIQUE_INSTYLE')<>1
   OR HAS_DBACCESS(N'POS_Instyle_Fragrance')<>1
    THROW 53303,'One of the fixed read-only sources is unavailable.',1;

IF EXISTS(
    SELECT 1
    FROM dbo.__codex_instyle_runway_merge_receipts
    WHERE IdempotencyKey=@OperatorIdempotencyKey
      AND PlanHash=@OperatorPlanHash
      AND CompletedAtUtc IS NOT NULL
)
BEGIN
    SELECT ResultJson
    FROM dbo.__codex_instyle_runway_merge_receipts
    WHERE IdempotencyKey=@OperatorIdempotencyKey
      AND PlanHash=@OperatorPlanHash;
    RETURN;
END;

DECLARE @RunId uniqueidentifier=NEWID(),
        @StartedAt datetime2(7)=SYSUTCDATETIME(),
        @LockResult int,
        @BackupTable sysname,
        @SourceRows bigint=0,
        @BackupRows bigint=0,
        @RowsUpdated bigint=0,
        @StatusMismatches bigint=0,
        @ResultJson nvarchar(max),
        @Sql nvarchar(max);

BEGIN TRY
    BEGIN TRANSACTION;
    EXEC @LockResult=sys.sp_getapplock
        @Resource=N'nova:instyle-runway:location-status-repair-v2',
        @LockMode=N'Exclusive',@LockOwner=N'Transaction',@LockTimeout=0;
    IF @LockResult<0
        THROW 53304,'Another fixed Instyle Runway operation is active.',1;

    IF (SELECT COUNT_BIG(*) FROM dbo.Locations)<>44
       OR (SELECT COUNT_BIG(*) FROM dbo.Regions)<>2
       OR (SELECT COUNT_BIG(*) FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Locations)<>24
       OR (SELECT COUNT_BIG(*) FROM [POS_Instyle_Fragrance].dbo.Locations)<>20
        THROW 53305,'The fixed 24/20/44 location contract changed.',1;

    IF EXISTS(
        SELECT 1
        FROM (VALUES(25),(26),(27),(28),(29),(31),(35),(36),(37),(39),(40),(42),(44))
             expected(TargetLocationID)
        LEFT JOIN dbo.Locations t ON t.LocationID=expected.TargetLocationID
        LEFT JOIN [POS_Instyle_Fragrance].dbo.Locations s
          ON s.LocationID=expected.TargetLocationID-24
        WHERE t.LocationID IS NULL
           OR s.LocationID IS NULL
           OR s.LocationManagerEmployeeID<>1
           OR t.LocationManagerEmployeeID<>1000000001
    )
        THROW 53306,'The reviewed thirteen-row inactive-location defect changed.',1;

    SELECT @StatusMismatches=COUNT_BIG(*)
    FROM (
        SELECT t.LocationID
        FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Locations s
        LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID
        WHERE t.LocationID IS NULL
           OR ISNULL(t.LocationManagerEmployeeID,-2147483648)
              <>ISNULL(s.LocationManagerEmployeeID,-2147483648)
        UNION ALL
        SELECT t.LocationID
        FROM [POS_Instyle_Fragrance].dbo.Locations s
        LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID+24
        WHERE t.LocationID IS NULL
           OR ISNULL(t.LocationManagerEmployeeID,-2147483648)
              <>ISNULL(CASE WHEN s.LocationManagerEmployeeID=1 THEN 1
                            WHEN s.LocationManagerEmployeeID>1
                              THEN s.LocationManagerEmployeeID+1000000000
                            ELSE s.LocationManagerEmployeeID END,-2147483648)
    ) mismatches;
    IF @StatusMismatches<>13
        THROW 53307,'The location-manager status mismatch scope is not exactly thirteen rows.',1;

    IF EXISTS(
        SELECT 1
        FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Locations s
        LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID
        WHERE t.LocationID IS NULL OR t.RegionID<>1
           OR ISNULL(t.LocationName,N'')<>ISNULL(s.LocationName,N'')
        UNION ALL
        SELECT 1
        FROM [POS_Instyle_Fragrance].dbo.Locations s
        LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID+24
        WHERE t.LocationID IS NULL OR t.RegionID<>2
           OR ISNULL(t.LocationName,N'')<>ISNULL(s.LocationName,N'')
    )
        THROW 53308,'The source-qualified location identity map changed.',1;

    SET @BackupTable=N'__codex_bak_runway_status_'+LEFT(@OperatorPlanHash,12);
    IF OBJECT_ID(N'dbo.'+@BackupTable,N'U') IS NOT NULL
        THROW 53309,'The retained location-status backup already exists for this plan.',1;
    SELECT @SourceRows=COUNT_BIG(*) FROM dbo.Locations;
    SET @Sql=N'SELECT * INTO dbo.'+QUOTENAME(@BackupTable)+
             N' FROM dbo.Locations; SELECT @RowsOut=COUNT_BIG(*) FROM dbo.'+
             QUOTENAME(@BackupTable)+N';';
    EXEC sys.sp_executesql @Sql,N'@RowsOut bigint OUTPUT',@RowsOut=@BackupRows OUTPUT;
    IF @BackupRows<>@SourceRows OR @BackupRows<>44
        THROW 53310,'The full Locations backup did not read back exactly.',1;
    INSERT dbo.__codex_instyle_runway_backup_manifest(
        PlanHash,IdempotencyKey,SourceTable,BackupTable,
        SourceRows,BackupRows,CreatedAtUtc
    ) VALUES(
        @OperatorPlanHash,@OperatorIdempotencyKey,N'Locations',@BackupTable,
        @SourceRows,@BackupRows,SYSUTCDATETIME()
    );

    INSERT dbo.__codex_instyle_runway_merge_receipts(
        IdempotencyKey,PlanHash,TargetStateHash,RunID,
        StartedAtUtc,CompletedAtUtc,ResultJson
    ) VALUES(
        @OperatorIdempotencyKey,@OperatorPlanHash,@ExpectedTargetStateHash,
        @RunId,@StartedAt,NULL,NULL
    );

    UPDATE t
    SET LocationManagerEmployeeID=1
    FROM dbo.Locations t
    JOIN [POS_Instyle_Fragrance].dbo.Locations s
      ON s.LocationID=t.LocationID-24
    WHERE t.LocationID IN(25,26,27,28,29,31,35,36,37,39,40,42,44)
      AND s.LocationManagerEmployeeID=1
      AND t.LocationManagerEmployeeID=1000000001;
    SET @RowsUpdated=@@ROWCOUNT;
    IF @RowsUpdated<>13
        THROW 53311,'The fixed location-status repair did not affect exactly thirteen rows.',1;

    SELECT @StatusMismatches=COUNT_BIG(*)
    FROM (
        SELECT t.LocationID
        FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Locations s
        LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID
        WHERE t.LocationID IS NULL
           OR ISNULL(t.LocationManagerEmployeeID,-2147483648)
              <>ISNULL(s.LocationManagerEmployeeID,-2147483648)
        UNION ALL
        SELECT t.LocationID
        FROM [POS_Instyle_Fragrance].dbo.Locations s
        LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID+24
        WHERE t.LocationID IS NULL
           OR ISNULL(t.LocationManagerEmployeeID,-2147483648)
              <>ISNULL(CASE WHEN s.LocationManagerEmployeeID=1 THEN 1
                            WHEN s.LocationManagerEmployeeID>1
                              THEN s.LocationManagerEmployeeID+1000000000
                            ELSE s.LocationManagerEmployeeID END,-2147483648)
    ) mismatches;
    IF @StatusMismatches<>0
        THROW 53312,'Source-authoritative location status did not read back.',1;

    SELECT @ResultJson=(
        SELECT N'completed' status,@RowsUpdated rowsUpdated,
               @BackupRows backupRows,@StatusMismatches locationStatusMismatches
        FOR JSON PATH,WITHOUT_ARRAY_WRAPPER
    );
    UPDATE dbo.__codex_instyle_runway_merge_receipts
    SET CompletedAtUtc=SYSUTCDATETIME(),ResultJson=@ResultJson
    WHERE IdempotencyKey=@OperatorIdempotencyKey
      AND PlanHash=@OperatorPlanHash;
    IF @@ROWCOUNT<>1
        THROW 53313,'The durable location-status receipt did not write.',1;

    COMMIT TRANSACTION;
    SELECT @ResultJson;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
"""


INSTYLE_RUNWAY_INVENTORY_HISTORY_CATCHUP_SQL_V3 = r"""
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME()<>N'POS_INSTYLE_RUNWAY'
    THROW 53401,'The connection is not bound to the fixed production target.',1;
IF @Apply<>1
    THROW 53402,'The fixed inventory-history catch-up requires apply mode.',1;
IF DB_ID(N'POS_LE_BOUTIQUE_INSTYLE') IS NULL
   OR DB_ID(N'POS_Instyle_Fragrance') IS NULL
   OR HAS_DBACCESS(N'POS_LE_BOUTIQUE_INSTYLE')<>1
   OR HAS_DBACCESS(N'POS_Instyle_Fragrance')<>1
    THROW 53403,'One of the fixed read-only sources is unavailable.',1;

IF EXISTS(
    SELECT 1 FROM dbo.__codex_instyle_runway_merge_receipts
    WHERE IdempotencyKey=@OperatorIdempotencyKey
      AND PlanHash=@OperatorPlanHash
      AND CompletedAtUtc IS NOT NULL
)
BEGIN
    SELECT ResultJson FROM dbo.__codex_instyle_runway_merge_receipts
    WHERE IdempotencyKey=@OperatorIdempotencyKey
      AND PlanHash=@OperatorPlanHash;
    RETURN;
END;

DECLARE @RunId uniqueidentifier=NEWID(),
        @StartedAt datetime2(7)=SYSUTCDATETIME(),
        @LockResult int,
        @BackupTable sysname,
        @SourceRows bigint=0,
        @BackupRows bigint=0,
        @ExpectedRows bigint=0,
        @RowsA bigint=0,
        @RowsB bigint=0,
        @FinalRows bigint=0,
        @ResultJson nvarchar(max),
        @Sql nvarchar(max);

BEGIN TRY
    BEGIN TRANSACTION;
    EXEC @LockResult=sys.sp_getapplock
        @Resource=N'nova:instyle-runway:inventory-history-catchup-v3',
        @LockMode=N'Exclusive',@LockOwner=N'Transaction',@LockTimeout=0;
    IF @LockResult<0
        THROW 53404,'Another fixed Instyle Runway operation is active.',1;

    IF (SELECT COUNT_BIG(*) FROM dbo.Locations)<>44
       OR (SELECT COUNT_BIG(*) FROM dbo.Regions)<>2
       OR NOT EXISTS(SELECT 1 FROM dbo.__codex_instyle_runway_product_map)
        THROW 53405,'The completed production merge foundation changed.',1;

    SELECT @SourceRows=COUNT_BIG(*) FROM dbo.InventoryHistoryItem;
    SELECT @ExpectedRows=
      (SELECT COUNT_BIG(*) FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.InventoryHistoryItem)+
      (SELECT COUNT_BIG(*) FROM [POS_Instyle_Fragrance].dbo.InventoryHistoryItem);
    IF @ExpectedRows<=@SourceRows
        THROW 53406,'There are no reviewed inventory-history rows to catch up.',1;

    SET @BackupTable=N'__codex_bak_runway_history_'+LEFT(@OperatorPlanHash,12);
    IF OBJECT_ID(N'dbo.'+@BackupTable,N'U') IS NOT NULL
        THROW 53407,'The retained inventory-history backup already exists for this plan.',1;
    SET @Sql=N'SELECT * INTO dbo.'+QUOTENAME(@BackupTable)+
             N' FROM dbo.InventoryHistoryItem; SELECT @RowsOut=COUNT_BIG(*) FROM dbo.'+
             QUOTENAME(@BackupTable)+N';';
    EXEC sys.sp_executesql @Sql,N'@RowsOut bigint OUTPUT',@RowsOut=@BackupRows OUTPUT;
    IF @BackupRows<>@SourceRows
        THROW 53408,'The full InventoryHistoryItem backup did not read back exactly.',1;
    INSERT dbo.__codex_instyle_runway_backup_manifest(
        PlanHash,IdempotencyKey,SourceTable,BackupTable,
        SourceRows,BackupRows,CreatedAtUtc
    ) VALUES(
        @OperatorPlanHash,@OperatorIdempotencyKey,N'InventoryHistoryItem',
        @BackupTable,@SourceRows,@BackupRows,SYSUTCDATETIME()
    );

    INSERT dbo.__codex_instyle_runway_merge_receipts(
        IdempotencyKey,PlanHash,TargetStateHash,RunID,
        StartedAtUtc,CompletedAtUtc,ResultJson
    ) VALUES(
        @OperatorIdempotencyKey,@OperatorPlanHash,@ExpectedTargetStateHash,
        @RunId,@StartedAt,NULL,NULL
    );

    SET IDENTITY_INSERT dbo.InventoryHistoryItem ON;
    INSERT dbo.InventoryHistoryItem(
        InventoryHistoryItemId,OriginalProductId,Category,Barcode,ProductName,
        Description,Size,Color,Quantity,FullCapacity,MinCapacity,InventoryHistoryId
    )
    SELECT s.InventoryHistoryItemId,
           CASE WHEN s.OriginalProductId>0 THEN COALESCE(
             (SELECT pm.TargetProductID
              FROM dbo.__codex_instyle_runway_product_map pm
              WHERE pm.SourceTag='A' AND pm.SourceProductID=s.OriginalProductId),
             CONVERT(bigint,s.OriginalProductId)-2000000000)
           ELSE s.OriginalProductId END,
           s.Category,s.Barcode,s.ProductName,s.Description,s.Size,s.Color,
           s.Quantity,s.FullCapacity,s.MinCapacity,s.InventoryHistoryId
    FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.InventoryHistoryItem s
    WHERE NOT EXISTS(
        SELECT 1 FROM dbo.InventoryHistoryItem t
        WHERE t.InventoryHistoryItemId=s.InventoryHistoryItemId
    );
    SET @RowsA=@@ROWCOUNT;

    INSERT dbo.InventoryHistoryItem(
        InventoryHistoryItemId,OriginalProductId,Category,Barcode,ProductName,
        Description,Size,Color,Quantity,FullCapacity,MinCapacity,InventoryHistoryId
    )
    SELECT CASE WHEN s.InventoryHistoryItemId>0
                THEN CONVERT(bigint,s.InventoryHistoryItemId)+1000000000
                ELSE s.InventoryHistoryItemId END,
           CASE WHEN s.OriginalProductId>0 THEN COALESCE(
             (SELECT pm.TargetProductID
              FROM dbo.__codex_instyle_runway_product_map pm
              WHERE pm.SourceTag='B' AND pm.SourceProductID=s.OriginalProductId),
             CONVERT(bigint,s.OriginalProductId)-1000000000)
           ELSE s.OriginalProductId END,
           s.Category,s.Barcode,s.ProductName,s.Description,s.Size,s.Color,
           s.Quantity,s.FullCapacity,s.MinCapacity,
           CASE WHEN s.InventoryHistoryId>0
                THEN CONVERT(bigint,s.InventoryHistoryId)+1000000000
                ELSE s.InventoryHistoryId END
    FROM [POS_Instyle_Fragrance].dbo.InventoryHistoryItem s
    WHERE NOT EXISTS(
        SELECT 1 FROM dbo.InventoryHistoryItem t
        WHERE t.InventoryHistoryItemId=CASE WHEN s.InventoryHistoryItemId>0
             THEN CONVERT(bigint,s.InventoryHistoryItemId)+1000000000
             ELSE s.InventoryHistoryItemId END
    );
    SET @RowsB=@@ROWCOUNT;
    SET IDENTITY_INSERT dbo.InventoryHistoryItem OFF;

    SELECT @FinalRows=COUNT_BIG(*) FROM dbo.InventoryHistoryItem;
    IF @RowsA+@RowsB<>@ExpectedRows-@SourceRows OR @FinalRows<>@ExpectedRows
        THROW 53409,'InventoryHistoryItem catch-up coverage is not exact.',1;

    SELECT @ResultJson=(
        SELECT N'completed' status,@RowsA sourceARows,@RowsB sourceBRows,
               @FinalRows finalRows,@BackupRows backupRows
        FOR JSON PATH,WITHOUT_ARRAY_WRAPPER
    );
    UPDATE dbo.__codex_instyle_runway_merge_receipts
    SET CompletedAtUtc=SYSUTCDATETIME(),ResultJson=@ResultJson
    WHERE IdempotencyKey=@OperatorIdempotencyKey
      AND PlanHash=@OperatorPlanHash;
    IF @@ROWCOUNT<>1
        THROW 53410,'The durable inventory-history receipt did not write.',1;

    COMMIT TRANSACTION;
    SELECT @ResultJson;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
"""
